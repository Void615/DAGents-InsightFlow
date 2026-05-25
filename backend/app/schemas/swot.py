from pydantic import BaseModel


class SWOTAnalysis(BaseModel):
    product: str
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]
    source_refs: dict[str, list[str]]
