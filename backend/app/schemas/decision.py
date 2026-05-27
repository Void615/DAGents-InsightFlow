from enum import Enum
from pydantic import BaseModel, Field


class DecisionAction(str, Enum):
    RESUME = "resume"
    JUMP = "jump"
    APPROVE = "approve"
    ABORT = "abort"


class DecisionRequest(BaseModel):
    action: DecisionAction
    target_node: str | None = Field(default=None, description="JUMP/RESUME 时指定的入口节点，覆盖 agent 的默认 target_node")
    feedback: str = Field(default="", description="人工反馈信息")
