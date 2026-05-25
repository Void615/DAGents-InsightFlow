from pydantic import BaseModel


class Sentiment(BaseModel):
    positive: int = 0
    negative: int = 0
    neutral: int = 0


class UserSentimentAnalysis(BaseModel):
    per_product: dict[str, Sentiment]
    common_praises: list[str]
    common_complaints: list[str]
