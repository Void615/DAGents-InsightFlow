from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.node_executor import NodeFatalError, execute_with_retry
from app.core.runtime.context import AgentContext, EventSink
from app.core.runtime.template import ArtifactDraft, NodeResult, NodeSpec
from app.db.models.artifact import Artifact
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.db.models.workflow_node_state import WorkflowNodeState
from app.exceptions import AppException
from app.services.event_service import EventLogger

_SKIP_SNAPSHOT_KEYS = {"messages", "raw_data"}


def sanitize_for_json(value) -> dict:
    if not isinstance(value, dict):
        return {}
    sanitized = {}
    for key, item in value.items():
        if key in _SKIP_SNAPSHOT_KEYS:
            continue
        try:
            sanitized[key] = json.loads(json.dumps(item, default=str))
        except (TypeError, ValueError):
            sanitized[key] = str(item)
    return sanitized


class NodeRunner:
    def __init__(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        run_id: uuid.UUID,
        execution_attempt: int,
        event_logger: EventLogger,
    ):
        self.db = db
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.execution_attempt = execution_attempt
        self.event_logger = event_logger

    async def run(self, spec: NodeSpec, state: dict) -> dict:
        data = dict(state.get("data") or {})
        control = dict(state.get("control") or {})
        runtime = dict(state.get("runtime") or {})
        iteration = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        node_logger = self.event_logger.with_node(spec.id, iteration)
        ctx = AgentContext(
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            node_id=spec.id,
            iteration=iteration,
            events=EventSink(node_logger, self.workflow_id, spec.id),
        )
        start = time.time()

        try:
            async def _agent_call(input_state: dict) -> dict:
                return await spec.agent.run(input_state, ctx)

            result = await execute_with_retry(
                _agent_call,
                data,
                spec.id,
                node_logger,
                retry_policy=spec.retry_policy,
            )
        except NodeFatalError as exc:
            duration_ms = int((time.time() - start) * 1000)
            err_msg = str(exc.last_error)
            if isinstance(exc.last_error, AppException):
                err_msg = exc.last_error.message
            await self._save_node_state(spec.id, iteration, data, control, duration_ms, True, err_msg)
            raise

        patch = {key: value for key, value in result.items() if not key.startswith("__")}
        node_result = NodeResult(patch=patch)
        new_data = {**data, **node_result.patch}
        if isinstance(node_result.patch.get("config"), dict):
            workflow = await get_workflow_by_uuid(self.db, self.workflow_id)
            if workflow:
                workflow.config = node_result.patch["config"]
        if "revision_count" in new_data:
            control["revision_count"] = new_data["revision_count"]
        if "max_revisions" in new_data:
            control["max_revisions"] = new_data["max_revisions"]
        control["current_node"] = spec.id
        control["last_node_completed_at"] = datetime.now(timezone.utc).isoformat()

        duration_ms = int((time.time() - start) * 1000)
        artifact_ids = await self._save_artifacts(spec, patch, new_data)
        snapshot = {
            "data": sanitize_for_json(new_data),
            "control": sanitize_for_json(control),
            "runtime": sanitize_for_json(runtime),
            "artifact_ids": [str(artifact_id) for artifact_id in artifact_ids],
        }
        await self._save_node_state(spec.id, iteration, snapshot, control, duration_ms)

        return {
            "data": new_data,
            "control": control,
            "runtime": runtime,
            "errors": list(state.get("errors") or []),
        }

    async def _save_node_state(
        self,
        node_name: str,
        iteration: int,
        state_snapshot: dict,
        control: dict,
        duration_ms: int = 0,
        is_error: bool = False,
        error_message: str | None = None,
    ) -> WorkflowNodeState:
        node_state = WorkflowNodeState(
            id=uuid.uuid4(),
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            execution_attempt=self.execution_attempt,
            node_name=node_name,
            iteration=iteration,
            state_snapshot=sanitize_for_json(state_snapshot),
            artifact_ids=[],
            duration_ms=duration_ms,
            is_error=is_error,
            error_message=error_message,
        )
        self.db.add(node_state)
        await self.db.commit()
        return node_state

    async def _save_artifacts(self, spec: NodeSpec, patch: dict, data: dict) -> list[uuid.UUID]:
        if spec.artifact_factory is None:
            return []
        artifact_ids: list[uuid.UUID] = []
        for draft in spec.artifact_factory(patch, data):
            artifact_ids.append(await self._save_artifact(draft))
        return artifact_ids

    async def _save_artifact(self, draft: ArtifactDraft) -> uuid.UUID:
        artifact = Artifact(
            id=uuid.uuid4(),
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            execution_attempt=self.execution_attempt,
            artifact_type=draft.artifact_type,
            title=draft.title,
            content=draft.content,
            content_text=draft.content_text,
            created_by_node=draft.created_by_node,
        )
        self.db.add(artifact)
        await self.db.commit()
        return artifact.id
