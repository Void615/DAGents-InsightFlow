from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from app.core.runtime.context import AgentContext
from pydantic import BaseModel, Field


class AgentLike(Protocol):
    async def run(self, state: dict, ctx: AgentContext) -> dict:
        ...


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    timeout_sec: int = 300
    backoff_base_sec: int = 2


class ArtifactDraft(BaseModel):
    artifact_type: str
    title: str
    content: dict
    created_by_node: str
    content_text: str | None = None


class NodeMetrics(BaseModel):
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model_name: str = ""


class NodeResult(BaseModel):
    patch: dict = Field(default_factory=dict)
    artifacts: list[ArtifactDraft] = Field(default_factory=list)
    metrics: NodeMetrics = Field(default_factory=NodeMetrics)


class PauseRequest(BaseModel):
    node_id: str
    reason: str = ""
    options: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    suggested_route: str | None = None

    def to_interrupt_payload(self, state: dict) -> dict:
        runtime = state.get("runtime") or {}
        return {
            "paused_by_node": self.node_id,
            "pause_reason": self.reason,
            "pause_options": self.options,
            "pause_context": self.context,
            "suggested_route": self.suggested_route,
            "run_id": runtime.get("run_id"),
            "thread_id": runtime.get("thread_id"),
        }


class ControlDecision(BaseModel):
    action: Literal["continue", "route", "pause", "finish", "fail"]
    next_node: str | None = None
    pause: PauseRequest | None = None
    reason: str = ""


class PausePolicy(Protocol):
    def build_pause(self, state: dict, spec: "NodeSpec") -> PauseRequest | None:
        ...


class RoutePolicy(Protocol):
    def decide(self, state: dict, spec: "NodeSpec") -> ControlDecision:
        ...


ArtifactFactory = Callable[[dict, dict], list[ArtifactDraft]]


@dataclass(frozen=True)
class NodeSpec:
    id: str
    agent: AgentLike
    default_next: str
    allowed_routes: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    pause_policy: PausePolicy | None = None
    route_policy: RoutePolicy | None = None
    artifact_factory: ArtifactFactory | None = None

    @property
    def gate_id(self) -> str:
        return f"{self.id}__gate"


@dataclass(frozen=True)
class GraphTemplate:
    name: str
    nodes: tuple[NodeSpec, ...]
    entrypoint: str

    def node(self, node_id: str) -> NodeSpec:
        for spec in self.nodes:
            if spec.id == node_id:
                return spec
        raise KeyError(f"Unknown node id: {node_id}")

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(spec.id for spec in self.nodes)
