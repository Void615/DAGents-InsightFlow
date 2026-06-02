import logging
import uuid
from datetime import datetime, timezone

from langgraph.errors import GraphInterrupt
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.checkpointer import get_checkpointer
from app.core.competitive_template import CompetitiveAnalysisTemplate
from app.core.node_executor import NodeFatalError
from app.core.runtime import GraphRuntime
from app.db.models.workflow_event import WorkflowEvent
from app.db.models.workflow_pause import WorkflowPause
from app.db.models.workflow_run import WorkflowRun
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.db.session import async_session_factory
from app.exceptions import AppException
from app.schemas.decision import DecisionRequest
from app.schemas.event import EventType
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager

logger = logging.getLogger(__name__)


def _thread_id(workflow_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"{workflow_id}:{run_id}"


def _session_factory_for_engine(engine: AsyncEngine | None):
    if engine is None:
        return async_session_factory
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _extract_error_info(e: Exception) -> tuple[str, str, dict | None]:
    if isinstance(e, NodeFatalError) and isinstance(e.last_error, AppException):
        app_err = e.last_error
        return app_err.error_code, app_err.message, app_err.details
    if isinstance(e, AppException):
        return e.error_code, e.message, e.details
    return "EXECUTION_ERROR", str(e)[:1000], None


def _extract_interrupt_payload(final_state: dict | None) -> dict | None:
    if not isinstance(final_state, dict) or "__interrupt__" not in final_state:
        return None
    interrupt_value = final_state.get("__interrupt__")
    if isinstance(interrupt_value, (list, tuple)) and interrupt_value:
        interrupt_value = interrupt_value[0]
    if hasattr(interrupt_value, "value"):
        interrupt_value = interrupt_value.value
    elif isinstance(interrupt_value, dict) and "value" in interrupt_value:
        interrupt_value = interrupt_value["value"]
    return interrupt_value if isinstance(interrupt_value, dict) else {}


def _state_data(final_state: dict | None) -> dict:
    if not isinstance(final_state, dict):
        return {}
    data = final_state.get("data")
    return data if isinstance(data, dict) else final_state


def _state_control(final_state: dict | None) -> dict:
    if not isinstance(final_state, dict):
        return {}
    control = final_state.get("control")
    return control if isinstance(control, dict) else {}


def _review_failed(final_state: dict | None) -> bool:
    review = _state_data(final_state).get("review_result")
    if not isinstance(review, dict):
        return False
    return review.get("passed") is False


def _review_failure_message(final_state: dict | None) -> str:
    review = _state_data(final_state).get("review_result")
    if isinstance(review, dict):
        return str(review.get("feedback") or "报告质检未通过")[:1000]
    return "报告质检未通过"


def _make_pause_state(pause_data: dict) -> dict:
    return {
        "paused_by_node": pause_data.get("paused_by_node", ""),
        "pause_reason": pause_data.get("pause_reason", ""),
        "pause_options": pause_data.get("pause_options", []),
        "pause_context": pause_data.get("pause_context", {}),
        "suggested_route": pause_data.get("suggested_route"),
        "run_id": pause_data.get("run_id"),
        "thread_id": pause_data.get("thread_id"),
        "dag_state": pause_data.get("dag_state", {}),
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }


def _initial_data(workflow) -> dict:
    return {
        "config": workflow.config,
        "competitors": [],
        "raw_data": {},
        "collection_errors": {},
        "context_summaries": {},
        "feature_matrix": None,
        "pricing_comparison": None,
        "user_sentiment": None,
        "swot": None,
        "report": None,
        "review_result": None,
        "revision_count": 0,
        "max_revisions": workflow.max_revisions,
        "current_phase": "collecting",
        "workflow_status": "running",
        "errors": [],
        "messages": [],
    }


async def _maybe_get_checkpointer(workflow_id: uuid.UUID):
    try:
        return await get_checkpointer()
    except RuntimeError as exc:
        logger.warning("工作流 %s 未初始化 checkpointer，跳过执行: %s", workflow_id, exc)
        return None


async def _get_or_create_run(db: AsyncSession, workflow) -> WorkflowRun:
    if workflow.current_run_id:
        current = await db.get(WorkflowRun, workflow.current_run_id)
        if current and current.status in ("running", "paused"):
            return current

    run = WorkflowRun(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        execution_attempt=workflow.execution_attempt,
        thread_id=_thread_id(workflow.id, uuid.uuid4()),
        status="running",
        entrypoint=CompetitiveAnalysisTemplate.entrypoint,
    )
    # Keep thread_id tied to the persisted run id.
    run.thread_id = _thread_id(workflow.id, run.id)
    db.add(run)
    workflow.current_run_id = run.id
    workflow.langgraph_checkpoint_id = run.thread_id
    await db.commit()
    await db.refresh(run)
    return run


async def _get_current_run(db: AsyncSession, workflow) -> WorkflowRun | None:
    if workflow.current_run_id:
        run = await db.get(WorkflowRun, workflow.current_run_id)
        if run:
            return run
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow.id)
        .order_by(WorkflowRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _make_runtime(db, workflow, run, event_logger, checkpointer) -> GraphRuntime:
    return GraphRuntime(
        template=CompetitiveAnalysisTemplate,
        db=db,
        workflow_id=workflow.id,
        run_id=run.id,
        execution_attempt=run.execution_attempt,
        thread_id=run.thread_id,
        event_logger=event_logger,
        checkpointer=checkpointer,
    )


async def _persist_pause(db: AsyncSession, workflow, run: WorkflowRun, pause_state: dict) -> None:
    previous = await db.execute(
        select(WorkflowPause).where(
            WorkflowPause.workflow_id == workflow.id,
            WorkflowPause.run_id == run.id,
            WorkflowPause.is_resolved.is_(False),
        )
    )
    for pause in previous.scalars().all():
        pause.is_resolved = True
        pause.resolved_at = datetime.now(timezone.utc)

    db.add(WorkflowPause(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        run_id=run.id,
        node_name=pause_state.get("paused_by_node") or "",
        reason=pause_state.get("pause_reason") or "",
        options=pause_state.get("pause_options") or [],
        context=pause_state.get("pause_context") or {},
        suggested_route=pause_state.get("suggested_route"),
    ))


async def _resolve_pause(db: AsyncSession, workflow, run: WorkflowRun, decision: dict) -> None:
    result = await db.execute(
        select(WorkflowPause).where(
            WorkflowPause.workflow_id == workflow.id,
            WorkflowPause.run_id == run.id,
            WorkflowPause.is_resolved.is_(False),
        )
    )
    for pause in result.scalars().all():
        pause.is_resolved = True
        pause.decision = decision
        pause.resolved_at = datetime.now(timezone.utc)


async def _handle_graph_result(workflow, run, db, event_logger: EventLogger, final_state: dict) -> None:
    pause_data = _extract_interrupt_payload(final_state)
    if pause_data is not None:
        workflow.status = "paused"
        workflow.current_phase = "reviewing"
        workflow.pause_state = _make_pause_state(pause_data)
        run.status = "paused"
        await _persist_pause(db, workflow, run, workflow.pause_state)
        await db.commit()
        await event_logger.log(EventType.WORKFLOW_PAUSED, workflow.pause_state, node_name=pause_data.get("paused_by_node", "review"))
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_PAUSED.value, **workflow.pause_state})
        return

    control = _state_control(final_state)
    data = _state_data(final_state)
    workflow.revision_count = int(control.get("revision_count", data.get("revision_count", 0)) or 0)

    if control.get("terminal_status") == "failed" or _review_failed(final_state):
        workflow.status = "failed"
        workflow.current_phase = "reviewing"
        workflow.error_message = control.get("terminal_reason") or _review_failure_message(final_state)
        run.status = "failed"
        run.error_message = workflow.error_message
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await event_logger.log(
            EventType.WORKFLOW_FAILED,
            {
                "error_code": "REVIEW_FAILED" if _review_failed(final_state) else "WORKFLOW_FAILED",
                "error_message": workflow.error_message,
                "error_details": data.get("review_result"),
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow.id, {
            "event_type": EventType.WORKFLOW_FAILED.value,
            "error_code": "REVIEW_FAILED",
            "error_message": workflow.error_message[:200],
        })
        return

    workflow.status = "completed"
    workflow.current_phase = "done"
    workflow.completed_at = datetime.now(timezone.utc)
    workflow.pause_state = None
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await event_logger.log(EventType.WORKFLOW_COMPLETE, {}, node_name="__workflow__")
    await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_COMPLETE.value})


async def _handle_graph_exception(workflow, run, db, event_logger: EventLogger, e: Exception) -> None:
    if isinstance(e, GraphInterrupt):
        pause_data = e.args[0] if e.args else {}
        workflow.status = "paused"
        workflow.pause_state = _make_pause_state(pause_data if isinstance(pause_data, dict) else {})
        run.status = "paused"
        await _persist_pause(db, workflow, run, workflow.pause_state)
        await db.commit()
        await event_logger.log(EventType.WORKFLOW_PAUSED, workflow.pause_state, node_name=workflow.pause_state.get("paused_by_node", "review"))
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_PAUSED.value, **workflow.pause_state})
        return

    logger.exception("工作流 %s 执行失败: %s", workflow.id, e)
    error_code, error_message, error_details = _extract_error_info(e)
    workflow.status = "failed"
    workflow.error_message = error_message
    run.status = "failed"
    run.error_message = error_message
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await event_logger.log(
        EventType.WORKFLOW_FAILED,
        {"error_code": error_code, "error_message": error_message, "error_details": error_details},
        node_name="__workflow__",
    )
    await sse_manager.broadcast(workflow.id, {
        "event_type": EventType.WORKFLOW_FAILED.value,
        "error_code": error_code,
        "error_message": error_message[:200],
    })


async def _get_last_event_time(db, workflow_id: uuid.UUID):
    result = await db.execute(
        select(sa_func.max(WorkflowEvent.created_at)).where(WorkflowEvent.workflow_id == workflow_id)
    )
    return result.scalar_one_or_none()


async def run_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "running":
            logger.warning("工作流 %s 不存在或状态不可执行", workflow_id)
            return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        run = await _get_or_create_run(db, workflow)
        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        await event_logger.log(EventType.WORKFLOW_START, {"config": workflow.config, "run_id": str(run.id)}, node_name="__workflow__")
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_START.value, "node_name": "__workflow__", "run_id": str(run.id)})

        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.ainvoke(_initial_data(workflow))
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)


async def resume_workflow(workflow_id: uuid.UUID, decision: DecisionRequest, engine: AsyncEngine | None = None) -> None:
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "paused":
            logger.warning("工作流 %s 不存在或状态不可恢复", workflow_id)
            return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        run = await _get_current_run(db, workflow)
        if not run:
            logger.error("工作流 %s 没有可恢复 run", workflow_id)
            return

        decision_payload = decision.model_dump(mode="json")
        await _resolve_pause(db, workflow, run, decision_payload)
        workflow.status = "running"
        workflow.pause_state = None
        run.status = "running"
        await db.commit()

        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        await event_logger.log(EventType.WORKFLOW_RESUMED, decision_payload, node_name="__workflow__")
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_RESUMED.value, **decision_payload})

        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.aresume(decision_payload)
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)


async def recover_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "running":
            logger.warning("工作流 %s 不存在或状态不可恢复", workflow_id)
            return

        last_event_time = await _get_last_event_time(db, workflow_id)
        if last_event_time is not None:
            age = (datetime.now(timezone.utc) - last_event_time.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 60:
                logger.info("工作流 %s 最近 %.0fs 前有事件，跳过恢复", workflow_id, age)
                return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        run = await _get_current_run(db, workflow)
        if not run:
            logger.error("工作流 %s 没有可恢复 run", workflow_id)
            return

        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.arecover()
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)
