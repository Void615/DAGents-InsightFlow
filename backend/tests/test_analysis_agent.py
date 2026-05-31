from app.agents.analysis_agent import AnalysisAgent
from app.schemas.feature import FeatureMatrix
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis


def test_analysis_outputs_are_restricted_to_collected_products():
    agent = AnalysisAgent()
    feature_matrix = FeatureMatrix.model_validate({
        "dimensions": ["硬件配置"],
        "matrix": [{
            "feature_name": "硬件配置",
            "products": {
                "三星S26": "有来源",
                "Pixel 10": "公开来源不足",
            },
        }],
    })
    pricing = PricingComparison.model_validate({
        "plans": [
            {"product": "三星S26", "tiers": [{"name": "公开信息", "price": 6999, "highlights": ["有来源"]}]},
            {"product": "Pixel 10", "tiers": [{"name": "公开信息", "price": 0, "highlights": ["公开来源不足"]}]},
        ],
        "summary": "summary",
    })
    sentiment = UserSentimentAnalysis.model_validate({
        "per_product": {
            "三星S26": {"positive": 1, "negative": 0, "neutral": 1},
            "Pixel 10": {"positive": 0, "negative": 0, "neutral": 1},
        },
        "common_praises": [],
        "common_complaints": [],
    })

    filtered_feature, filtered_pricing, filtered_sentiment = agent._restrict_to_products(
        feature_matrix,
        pricing,
        sentiment,
        ["三星S26"],
    )

    assert filtered_feature.matrix[0].products == {"三星S26": "有来源"}
    assert [plan.product for plan in filtered_pricing.plans] == ["三星S26"]
    assert set(filtered_sentiment.per_product) == {"三星S26"}
