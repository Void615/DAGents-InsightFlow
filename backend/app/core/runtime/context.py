from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.schemas.event import EventType
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager


class EventSink:
    """Agent-facing event boundary.

    Agents emit semantic events through this sink; the sink owns persistence and
    realtime broadcast details.
    """

    def __init__(self, event_logger: EventLogger, workflow_id: uuid.UUID, node_name: str):
        self.event_logger = event_logger
        self.workflow_id = workflow_id
        self.node_name = node_name

    async def emit(self, event_type: EventType, payload: dict | None = None) -> None:
        event = await self.event_logger.log(event_type=event_type, payload=payload or {})
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": event_type.value,
            "node_name": event.node_name or self.node_name,
            "seq": event.seq,
            "payload": payload or {},
            "created_at": str(event.created_at),
        })

    async def progress(self, *, stage: str, message: str, level: str = "info") -> None:
        await self.emit(
            EventType.NODE_PROGRESS,
            {
                "stage": stage,
                "message": message,
                "level": level,
            },
        )

    async def stream_token(self, token: str) -> None:
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": EventType.LLM_STREAM.value,
            "node_name": self.node_name,
            "content": token,
        })


@dataclass(frozen=True)
class AgentContext:
    workflow_id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    iteration: int
    events: EventSink
    llm: Any = None
    tools: Any = None
