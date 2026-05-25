from typing import Optional
from pydantic import BaseModel


class ReviewCheck(BaseModel):
    dimension: str
    passed: bool
    detail: str


class ReviewOutput(BaseModel):
    passed: bool
    score: float
    checks: list[ReviewCheck]
    feedback: str
    target_node: Optional[str] = None
    specific_issues: list[str]
