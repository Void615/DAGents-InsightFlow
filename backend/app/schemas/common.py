from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    url: str
    title: str
    snippet: str
    confidence: float = 0.7


class ErrorRecord(BaseModel):
    error_code: str
    error_message: str
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class CompressedClaim(BaseModel):
    claim: str
    source_indices: list[int]


class CompressedSummary(BaseModel):
    product_name: str
    summary: str
    key_claims: list[CompressedClaim]
    source_urls: list[str]
