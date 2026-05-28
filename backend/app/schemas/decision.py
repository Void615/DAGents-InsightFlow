from enum import Enum
from pydantic import BaseModel, Field


class DecisionAction(str, Enum):
    JUMP = "jump"
    APPROVE = "approve"
    ABORT = "abort"


class DecisionRequest(BaseModel):
    action: DecisionAction
    target_node: str | None = Field(
        default=None,
        description="jump 时指定跳转目标节点。为空时 fallback 到 agent 建议的 target_node",
    )
    feedback: str = Field(default="", description="人工反馈信息")
