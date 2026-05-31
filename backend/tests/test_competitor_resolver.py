import pytest

from app.agents.competitor_resolver import (
    detect_subcategory,
    extract_candidate_names,
    is_valid_competitor_name,
    resolve_competitors,
)
from app.schemas.workflow import ProductProfile
from app.services.interview_service import suggest_competitors


class FakeSearchClient:
    async def search(self, query: str, max_results: int = 5, **kwargs):
        return {
            "results": [
                {
                    "title": "小米15 Ultra 对比 OPPO Find X8 Ultra、vivo X200 Ultra、荣耀 Magic7 RSR",
                    "content": "同档影像旗舰还包括三星 Galaxy S25 Ultra 与华为 Pura 70 Ultra。",
                },
                {
                    "title": "小米15 Ultra 与 Xiaomi 15 Ultra 参数评测",
                    "content": "这是目标产品别名，不应被当成竞品。",
                },
            ]
        }


class FakeDroneSearchClient:
    async def search(self, query: str, max_results: int = 5, **kwargs):
        return {
            "results": [
                {
                    "title": "大疆 Air 3S 竞品：Autel EVO Lite、HoverAir X1 Pro、Skydio 2",
                    "content": "这些航拍无人机在影像、避障、图传和续航上形成对比。",
                }
            ]
        }


class FakeSaaSSearchClient:
    async def search(self, query: str, max_results: int = 5, **kwargs):
        return {
            "results": [
                {
                    "title": "Notion alternatives: Coda, Confluence, ClickUp, Airtable",
                    "content": "协作文档、知识库和项目管理场景常见竞品还包括飞书和语雀。",
                }
            ]
        }


class FakeGenericAppSearchClient:
    async def search(self, query: str, max_results: int = 5, **kwargs):
        return {
            "results": [
                {
                    "title": "小红书探店旅游攻略竞品：大众点评、马蜂窝、携程旅行、抖音",
                    "content": "这些产品都覆盖本地生活、旅游攻略或内容种草场景。",
                },
                {
                    "title": "小红书种草，大众点评拔草，年轻人不好骗了？",
                    "content": "文章讨论小红书与大众点评在消费决策场景中的关系。",
                },
            ]
        }


class FakeStandardPhoneSearchClient:
    async def search(self, query: str, max_results: int = 5, **kwargs):
        return {
            "results": [
                {
                    "title": "三星S26 标准款竞品：iPhone 16 Pro、iPhone 16、华为Mate 70 Pro、华为Mate 70、小米15 Ultra、小米15",
                    "content": "标准款横向对比应优先选择同层级机型，而不是 Pro 或 Ultra。",
                }
            ]
        }


class FakeTwoStepStandardPhoneSearchClient:
    def __init__(self):
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 5, **kwargs):
        self.queries.append(query)
        if len(self.queries) == 1:
            return {
                "results": [
                    {
                        "title": "三星S26 竞品包括 iPhone 17 Pro Max、Xiaomi 17 Ultra、Samsung Galaxy S26 Ultra",
                        "content": "第一轮结果偏向高配版本或同系列变体。",
                    }
                ]
            }
        return {
            "results": [
                {
                    "title": "三星S26 标准款同层级竞品：Pixel 10、OnePlus 15、Xiaomi 17、iPhone 17、华为Mate 70",
                    "content": "这些标准款旗舰手机适合与标准款 Galaxy S26 横向对比。",
                }
            ]
        }


def test_detects_supported_subcategories():
    assert detect_subcategory("小米15 Ultra", "硬件产品") == "smartphone"
    assert detect_subcategory("大疆 Air 3S", "硬件产品") == "drone"
    assert detect_subcategory("Notion", "SaaS / 协作工具") == "saas_workspace"
    assert detect_subcategory(
        "未收录品牌 X1",
        "硬件产品",
        ProductProfile(market_category="smartphone"),
    ) == "smartphone"


def test_invalid_hardware_competitor_names_are_rejected():
    invalid_names = ["電腦王阿達", "Google TV", "全智慧校正", "採系統化學習法", "台哥大"]

    for name in invalid_names:
        ok, reason = is_valid_competitor_name(name, "小米15 Ultra", "硬件产品")
        assert not ok
        assert reason in {"looks_like_non_product_entity", "missing_smartphone_product_hint"}


def test_profile_rejects_same_series_variant_and_conversation_fragments():
    profile = ProductProfile(
        canonical_name="Samsung Galaxy S26",
        product_form="hardware",
        market_category="smartphone",
        brand="Samsung",
        product_line="Galaxy S",
        model="S26",
        variant_tier="standard",
        market_segment="flagship smartphone",
        competition_basis=["same category", "similar price band"],
        exclude_relations=["same brand same series variant", "non-product phrase"],
    )

    ok, reason = is_valid_competitor_name("三星S26 Ultra", "三星S26", "硬件产品", profile)
    assert not ok
    assert reason == "same_series_variant"

    ok, reason = is_valid_competitor_name("我用Peak Design Mount 好多年了", "三星S26", "硬件产品", profile)
    assert not ok
    assert reason == "looks_like_non_product_phrase"

    ok, reason = is_valid_competitor_name("iPhone 16 Pro", "三星S26", "硬件产品", profile)
    assert not ok
    assert reason == "tier_mismatch"


def test_generic_rejects_category_descriptors_and_natural_language_fragments():
    profile = ProductProfile(
        canonical_name="小红书",
        product_form="mobile application",
        market_category="lifestyle UGC content community app",
        market_segment="生活种草与消费决策平台",
    )

    ok, reason = is_valid_competitor_name("至于探店或者旅游攻略", "小红书", "移动应用", profile)
    assert not ok
    assert reason == "looks_like_non_product_phrase"

    ok, reason = is_valid_competitor_name("垂直探店/旅游攻略类内容产品", "小红书", "移动应用", profile)
    assert not ok
    assert reason == "category_descriptor"

    ok, reason = is_valid_competitor_name("大众点评", "小红书", "移动应用", profile)
    assert ok
    assert reason == "accepted"


def test_generic_rejects_gibberish_competitor_names():
    profile = ProductProfile(
        canonical_name="淘宝",
        product_form="mobile application",
        market_category="comprehensive C-end e-commerce mobile app",
        market_segment="综合电商平台",
    )

    for name in ["AfҜ}ՌXijVe寀", "\" AYTN~]Q7"]:
        ok, reason = is_valid_competitor_name(name, "淘宝", "移动应用", profile)
        assert not ok
        assert reason == "looks_like_gibberish_entity"

    ok, reason = is_valid_competitor_name("京东", "淘宝", "移动应用", profile)
    assert ok
    assert reason == "accepted"


def test_extracts_smartphone_candidates_from_search_text():
    text = "OPPO Find X8 Ultra、vivo X200 Ultra、荣耀 Magic7 RSR、三星 Galaxy S25 Ultra、iPhone 16、小米15"

    assert extract_candidate_names(text) == [
        "OPPO Find X8 Ultra",
        "vivo X200 Ultra",
        "荣耀 Magic7 RSR",
        "三星 Galaxy S25 Ultra",
        "iPhone 16",
        "小米15",
    ]


@pytest.mark.asyncio
async def test_resolver_replaces_invalid_competitors_with_search_candidates():
    resolution = await resolve_competitors(
        client=FakeSearchClient(),
        target_product="小米15 Ultra",
        category="硬件产品",
        focus_dimensions=["硬件配置", "影像表现", "续航充电"],
        competitor_names=["電腦王阿達", "Google TV", "全智慧校正"],
        competitor_count=3,
    )

    assert resolution.competitors == [
        "OPPO Find X8 Ultra",
        "vivo X200 Ultra",
        "荣耀 Magic7 RSR",
    ]
    assert resolution.added == resolution.competitors
    assert {item["name"] for item in resolution.dropped} >= {"電腦王阿達", "Google TV", "全智慧校正"}
    assert "小米15 Ultra" in resolution.query


@pytest.mark.asyncio
async def test_resolver_preserves_valid_user_competitors_before_supplementing():
    resolution = await resolve_competitors(
        client=FakeSearchClient(),
        target_product="小米15 Ultra",
        category="硬件产品",
        focus_dimensions=["影像表现"],
        competitor_names=["OPPO Find X8 Ultra", "Google TV"],
        competitor_count=3,
    )

    assert resolution.competitors == [
        "OPPO Find X8 Ultra",
        "vivo X200 Ultra",
        "荣耀 Magic7 RSR",
    ]
    assert resolution.added == ["vivo X200 Ultra", "荣耀 Magic7 RSR"]


@pytest.mark.asyncio
async def test_resolver_prefers_same_variant_tier_for_standard_phone():
    profile = ProductProfile(
        canonical_name="Samsung Galaxy S26",
        product_form="hardware",
        market_category="smartphone",
        brand="Samsung",
        product_line="Galaxy S",
        model="S26",
        variant_tier="standard",
        market_segment="flagship smartphone",
        competition_basis=["same category", "same variant tier preferred"],
        exclude_relations=["different SKU tier unless explicitly requested"],
    )

    resolution = await resolve_competitors(
        client=FakeStandardPhoneSearchClient(),
        target_product="三星S26",
        category="硬件产品",
        focus_dimensions=["硬件配置", "影像表现"],
        competitor_names=["iPhone 16 Pro", "华为Mate 70 Pro", "小米15 Ultra"],
        competitor_count=3,
        product_profile=profile,
    )

    assert resolution.competitors == ["iPhone 16", "华为Mate 70", "小米15"]
    assert {item["name"] for item in resolution.dropped} >= {"iPhone 16 Pro", "华为Mate 70 Pro", "小米15 Ultra"}
    assert {item["reason"] for item in resolution.dropped} >= {"tier_mismatch"}


@pytest.mark.asyncio
async def test_resolver_runs_second_same_tier_search_when_first_search_only_finds_high_tier():
    client = FakeTwoStepStandardPhoneSearchClient()
    profile = ProductProfile(
        canonical_name="Samsung Galaxy S26",
        product_form="hardware",
        market_category="smartphone",
        brand="Samsung",
        product_line="Galaxy S",
        model="S26",
        variant_tier="standard",
        market_segment="flagship smartphone",
        competition_basis=["same category", "same variant tier preferred"],
        exclude_relations=["different SKU tier unless explicitly requested"],
    )

    resolution = await resolve_competitors(
        client=client,
        target_product="三星S26",
        category="硬件产品",
        focus_dimensions=["硬件配置", "影像表现"],
        competitor_names=["iPhone 17 Pro Max", "Xiaomi 17 Ultra"],
        competitor_count=3,
        product_profile=profile,
    )

    assert len(client.queries) == 2
    assert "标准款" in client.queries[1]
    assert resolution.competitors == ["Pixel 10", "OnePlus 15", "Xiaomi 17"]
    assert {item["reason"] for item in resolution.dropped} >= {"tier_mismatch", "same_series_variant"}


@pytest.mark.asyncio
async def test_resolver_uses_drone_strategy_for_dji_products():
    resolution = await resolve_competitors(
        client=FakeDroneSearchClient(),
        target_product="大疆 Air 3S",
        category="硬件产品",
        focus_dimensions=["影像表现", "避障能力", "续航"],
        competitor_names=["Google TV", "手机摄影教程"],
        competitor_count=3,
    )

    assert resolution.subcategory == "drone"
    assert resolution.competitors == ["Autel EVO Lite", "HoverAir X1 Pro", "Skydio 2"]
    assert {item["name"] for item in resolution.dropped} >= {"Google TV", "手机摄影教程"}


@pytest.mark.asyncio
async def test_resolver_uses_saas_workspace_strategy():
    resolution = await resolve_competitors(
        client=FakeSaaSSearchClient(),
        target_product="Notion",
        category="SaaS / 协作工具",
        focus_dimensions=["协作文档", "知识库", "项目管理"],
        competitor_names=["小米15 Ultra", "博客"],
        competitor_count=3,
    )

    assert resolution.subcategory == "saas_workspace"
    assert resolution.competitors == ["Coda", "Confluence", "ClickUp"]
    assert {item["name"] for item in resolution.dropped} >= {"小米15 Ultra", "博客"}


@pytest.mark.asyncio
async def test_generic_resolver_uses_descriptors_as_search_terms_not_competitors():
    profile = ProductProfile(
        canonical_name="小红书",
        product_form="mobile application",
        market_category="lifestyle UGC content community app",
        market_segment="生活种草与消费决策平台",
        competition_basis=["探店", "旅游攻略", "消费决策"],
    )

    resolution = await resolve_competitors(
        client=FakeGenericAppSearchClient(),
        target_product="小红书",
        category="移动应用",
        focus_dimensions=["用户增长", "内容生态差异"],
        competitor_names=["至于探店或者旅游攻略"],
        competitor_count=3,
        product_profile=profile,
    )

    assert resolution.subcategory == "generic"
    assert resolution.competitors == ["大众点评", "马蜂窝", "携程旅行"]
    assert {"name": "至于探店或者旅游攻略", "reason": "looks_like_non_product_phrase"} in resolution.dropped
    assert "探店" in resolution.query
    assert "旅游攻略" in resolution.query


@pytest.mark.asyncio
async def test_interview_suggestions_validate_existing_competitors(monkeypatch):
    import app.services.interview_service as interview_service

    client = FakeSearchClient()
    monkeypatch.setattr(interview_service, "_get_tavily_client", lambda: client)

    competitors = await suggest_competitors(
        target_product="小米15 Ultra",
        category="硬件产品",
        focus_dimensions=["硬件配置", "影像表现"],
        existing_competitors=["電腦王阿達", "Google TV", "全智慧校正"],
        competitor_count=3,
    )

    assert competitors == [
        "OPPO Find X8 Ultra",
        "vivo X200 Ultra",
        "荣耀 Magic7 RSR",
    ]
