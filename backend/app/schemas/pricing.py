from pydantic import BaseModel


class PricingTier(BaseModel):
    name: str
    price: float
    highlights: list[str]


class PricingPlan(BaseModel):
    product: str
    tiers: list[PricingTier]


class PricingComparison(BaseModel):
    plans: list[PricingPlan]
    summary: str
