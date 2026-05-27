from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.schemas.auth import UserResponse
from app.schemas.workflow import WorkflowCreate
from app.schemas.decision import DecisionRequest
from app.db.queries.workflow_queries import get_workflow_by_id, get_user_workflows
from app.services.workflow_service import create_workflow, start_workflow, cancel_workflow, delete_workflow
from app.services.sse_service import sse_manager
from app.core.workflow_executor import run_workflow, resume_workflow
from app.exceptions import WorkflowNotFoundError, InvalidStateTransitionError


router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_new_workflow(
    body: WorkflowCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await create_workflow(db, current_user.id, body.title)
    return {"workflow_id": str(workflow.id), "title": workflow.title, "status": workflow.status}


@router.get("")
async def list_my_workflows(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflows = await get_user_workflows(db, current_user.id)
    return [{"id": str(w.id), "title": w.title, "status": w.status, "created_at": w.created_at} for w in workflows]


@router.get("/{workflow_id}")
async def get_workflow_detail(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    return {
        "id": str(workflow.id),
        "title": workflow.title,
        "status": workflow.status,
        "current_phase": workflow.current_phase,
        "config": workflow.config,
        "revision_count": workflow.revision_count,
        "max_revisions": workflow.max_revisions,
        "total_tokens": workflow.total_tokens,
        "error_message": workflow.error_message,
        "pause_state": workflow.pause_state,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "completed_at": workflow.completed_at,
    }


@router.post("/{workflow_id}/start")
async def start_workflow_endpoint(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """确认配置后启动 DAG 执行。"""
    workflow = await start_workflow(db, workflow_id, current_user.id)
    background_tasks.add_task(run_workflow, workflow.id)
    return {"workflow_id": str(workflow.id), "status": workflow.status}


@router.delete("/{workflow_id}")
async def delete_workflow_endpoint(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """删除工作流。运行中的工作流会先取消再删除。"""
    await cancel_workflow(db, workflow_id, current_user.id)
    await delete_workflow(db, workflow_id, current_user.id)
    return {"detail": "工作流已删除"}


@router.post("/{workflow_id}/retry/{node_name}")
async def retry_node_endpoint(
    workflow_id: str,
    node_name: str,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """重试失败的工作流，从零开始重新执行。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status not in ("failed", "paused"):
        raise InvalidStateTransitionError(workflow_id, workflow.status, "retry")
    workflow.status = "running"
    workflow.error_message = None
    workflow.execution_attempt += 1
    await db.commit()
    background_tasks.add_task(run_workflow, workflow.id)
    return {
        "workflow_id": str(workflow.id),
        "status": "running",
        "execution_attempt": workflow.execution_attempt,
        "retry_node": node_name,
    }


@router.post("/{workflow_id}/decide")
async def human_decide(
    workflow_id: str,
    decision: DecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """人在回路决策端点。

    - resume: 从 checkpoint 继续执行（agent 建议的 target_node）
    - jump:   从 checkpoint 恢复，使用指定的 target_node 重新执行
    - approve: 强制接受当前结果，标记 completed
    - abort:   放弃执行，标记 cancelled
    """
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "paused":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "decide")

    if decision.action == "approve":
        workflow.status = "completed"
        workflow.current_phase = "done"
        workflow.pause_state = None
        await db.commit()
        await sse_manager.close_workflow(workflow.id)
        return {"workflow_id": str(workflow.id), "status": "completed", "action": "approve"}

    if decision.action == "abort":
        workflow.status = "cancelled"
        workflow.pause_state = None
        await db.commit()
        await sse_manager.close_workflow(workflow.id)
        return {"workflow_id": str(workflow.id), "status": "cancelled", "action": "abort"}

    # resume / jump: 启动后台恢复任务
    background_tasks.add_task(resume_workflow, workflow.id, decision)
    return {
        "workflow_id": str(workflow.id),
        "status": "running",
        "action": decision.action.value,
        "target_node": decision.target_node,
    }
