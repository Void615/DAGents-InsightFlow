from pydantic import BaseModel


class FeatureItem(BaseModel):
    feature_name: str
    products: dict[str, str]


class FeatureMatrix(BaseModel):
    dimensions: list[str]
    matrix: list[FeatureItem]
