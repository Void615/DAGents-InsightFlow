from __future__ import annotations

import uuid
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime.node_runner import NodeRunner
from app.core.runtime.policies import DefaultRoutePolicy
from app.core.runtime.template import GraphTemplate, NodeSpec
from app.schemas.event import EventType
from app.schemas.runtime_state import RuntimeState
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager


class GraphRuntime:
    """Reusable StateGraph runtime.

    It compiles a GraphTemplate into the standard shape:
    business_node -> control_gate -> next business node / END.
    """

    def __init__(
        self,
        template: GraphTemplate,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        run_id: uuid.UUID,
        execution_attempt: int,
        thread_id: str,
        event_logger: EventLogger,
        checkpointer=None,
    ):
        self.template = template
        self.db = db
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.execution_attempt = execution_attempt
        self.thread_id = thread_id
        self.event_logger = event_logger
        self.checkpointer = checkpointer

    @property
    def config(self) -> dict:
        return {"configurable": {"thread_id": self.thread_id}}

    def initial_state(self, data: dict) -> RuntimeState:
        revision_count = int(data.get("revision_count", 0) or 0)
        max_revisions = int(data.get("max_revisions", 3) or 3)
        return {
            "data": data,
            "control": {
                "current_node": self.template.entrypoint,
                "revision_count": revision_count,
                "max_revisions": max_revisions,
                "route_label": self.template.entrypoint,
                "terminal_status": None,
            },
            "runtime": {
                "workflow_id": str(self.workflow_id),
                "run_id": str(self.run_id),
                "execution_attempt": self.execution_attempt,
                "thread_id": self.thread_id,
                "template": self.template.name,
            },
            "errors": [],
        }

    def compile(self):
        graph = StateGraph(RuntimeState)
        runner = NodeRunner(
            self.db,
            self.workflow_id,
            self.run_id,
            self.execution_attempt,
            self.event_logger,
        )

        for spec in self.template.nodes:
            graph.add_node(spec.id, self._make_business_node(runner, spec))
            graph.add_node(spec.gate_id, self._make_gate_node(spec))
            graph.add_edge(spec.id, spec.gate_id)
            graph.add_conditional_edges(spec.gate_id, self._gate_router, self._gate_mapping(spec))

        graph.set_entry_point(self.template.entrypoint)
        return graph.compile(checkpointer=self.checkpointer)

    async def ainvoke(self, data: dict):
        return await self.compile().ainvoke(self.initial_state(data), self.config)

    async def aresume(self, decision: dict):
        return await self.compile().ainvoke(Command(resume=decision), self.config)

    async def arecover(self):
        return await self.compile().ainvoke(None, self.config)

    def _make_business_node(self, runner: NodeRunner, spec: NodeSpec):
        async def _node(state: RuntimeState) -> RuntimeState:
            return await runner.run(spec, dict(state))

        return _node

    def _make_gate_node(self, spec: NodeSpec):
        async def _gate(state: RuntimeState) -> RuntimeState:
            current_state = dict(state)
            data = dict(current_state.get("data") or {})
            control = dict(current_state.get("control") or {})

            if spec.pause_policy is not None:
                pause = spec.pause_policy.build_pause({"data": data, "control": control, "runtime": current_state.get("runtime") or {}}, spec)
                if pause is not None:
                    payload = pause.to_interrupt_payload(current_state)
                    decision = interrupt(payload)
                    if isinstance(decision, dict):
                        control["human_decision"] = decision
                    control["last_pause"] = payload

            route_policy = spec.route_policy or DefaultRoutePolicy()
            decision = route_policy.decide({"data": data, "control": control, "runtime": current_state.get("runtime") or {}}, spec)
            route_label = decision.next_node or "done"

            if decision.action == "route" and decision.next_node:
                if spec.id == "review":
                    next_revision = int(control.get("revision_count", data.get("revision_count", 0)) or 0) + 1
                    control["revision_count"] = next_revision
                    data["revision_count"] = next_revision
                await self._emit_reroute(spec.id, decision.next_node, control)
            elif decision.action == "finish":
                route_label = "done"
                control["terminal_status"] = "completed"
            elif decision.action == "fail":
                route_label = "fail"
                control["terminal_status"] = "failed"
                control["terminal_reason"] = decision.reason

            control["route_label"] = route_label
            control["last_decision"] = decision.model_dump(mode="json")
            control["last_gate_completed_at"] = datetime.now(timezone.utc).isoformat()
            return {
                "data": data,
                "control": control,
                "runtime": dict(current_state.get("runtime") or {}),
                "errors": list(current_state.get("errors") or []),
            }

        return _gate

    def _gate_router(self, state: RuntimeState) -> str:
        return (state.get("control") or {}).get("route_label") or "done"

    def _gate_mapping(self, spec: NodeSpec) -> dict:
        targets = set(self.template.node_ids)
        targets.update(spec.allowed_routes)
        if spec.default_next != "done":
            targets.add(spec.default_next)
        mapping = {target: target for target in targets}
        mapping["done"] = END
        mapping["fail"] = END
        return mapping

    async def _emit_reroute(self, from_node: str, to_node: str, control: dict) -> None:
        human_decision = control.get("human_decision") or {}
        event = await self.event_logger.log(
            event_type=EventType.REROUTE,
            payload={
                "from_node": from_node,
                "to_node": to_node,
                "trigger": "human_jump" if human_decision.get("action") == "jump" else "policy",
                "feedback": human_decision.get("feedback", ""),
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": EventType.REROUTE.value,
            "node_name": event.node_name,
            "seq": event.seq,
            "from_node": from_node,
            "to_node": to_node,
        })
