import json
import re
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.schemas.workflow import ProductProfile


class SearchClient(Protocol):
    async def search(self, query: str, max_results: int = 5, **kwargs): ...


PROFILE_SYSTEM_PROMPT = """你是产品竞品分析前置画像助手。
你的任务是根据目标产品、用户选择的粗粒度产品形态和少量搜索摘要，输出一个用于竞品选择的结构化产品画像。

要求：
- 只输出 JSON，不要 markdown，不要解释。
- 不要推荐竞品，只描述目标产品本身和竞品选择边界。
- market_category 使用简洁英文短语，例如 smartphone、AI coding assistant、EV、cloud database、food delivery platform。
- variant_tier 描述目标产品的 SKU 层级：standard、pro、ultra、plus、max、mini、air、unknown；标准款必须填 standard。
- competition_basis 描述应该满足的竞品边界。
- exclude_relations 描述应该排除的候选关系，例如 same brand same series variant、accessory、media/site/forum、non-product phrase。
"""


def fallback_product_profile(target_product: str, category: str) -> ProductProfile:
    """Create a conservative profile when LLM/search profiling is unavailable."""
    form_by_category = {
        "硬件产品": "hardware",
        "SaaS / 协作工具": "software",
        "移动应用": "mobile app",
    }
    return ProductProfile(
        canonical_name=target_product,
        product_form=form_by_category.get(category, category),
        market_category="",
        brand="",
        product_line="",
        model="",
        variant_tier=_infer_variant_tier(target_product),
        market_segment="",
        competition_basis=["same category", "similar user need", "similar price or adoption tier", "same variant tier preferred"],
        exclude_relations=[
            "same brand same series variant",
            "different SKU tier unless explicitly requested",
            "accessory",
            "media/site/forum",
            "non-product phrase",
        ],
    )


async def build_product_profile(
    *,
    target_product: str,
    category: str,
    focus_dimensions: list[str],
    existing_profile: ProductProfile | dict[str, Any] | None = None,
    client: SearchClient | None = None,
) -> ProductProfile:
    """Infer an editable target-product profile for competitor selection.

    The LLM output is treated as a hypothesis and merged into a conservative
    fallback so profiling failures do not block interview completion.
    """
    fallback = _merge_profile(fallback_product_profile(target_product, category), existing_profile)

    settings = get_settings()
    if not settings.LLM_API_KEY or not settings.LLM_MODEL:
        return fallback

    evidence = await _search_profile_evidence(client, target_product, category)
    prompt = {
        "target_product": target_product,
        "coarse_product_category": category,
        "focus_dimensions": focus_dimensions[:6],
        "existing_profile": fallback.model_dump(mode="json"),
        "search_evidence": evidence,
        "output_schema": {
            "canonical_name": "string",
            "product_form": "string",
            "market_category": "string",
            "brand": "string",
            "product_line": "string",
            "model": "string",
            "variant_tier": "standard | pro | ultra | plus | max | mini | air | unknown",
            "market_segment": "string",
            "competition_basis": ["string"],
            "exclude_relations": ["string"],
        },
    }

    try:
        llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=0,
        )
        response = await llm.ainvoke([
            SystemMessage(content=PROFILE_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
        ])
        content = response.content
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        data = _extract_json_object(str(content))
        return _merge_profile(fallback, data)
    except Exception:
        return fallback


async def _search_profile_evidence(client: SearchClient | None, target_product: str, category: str) -> list[dict[str, str]]:
    if client is None:
        return []
    try:
        response = await client.search(
            query=f"{target_product} {category} 是什么 产品 定位 竞品",
            max_results=4,
            search_depth="basic",
            include_answer=False,
        )
    except Exception:
        return []

    evidence: list[dict[str, str]] = []
    for item in response.get("results", []):
        if not isinstance(item, dict):
            continue
        evidence.append({
            "title": str(item.get("title", ""))[:200],
            "content": str(item.get("content") or item.get("snippet") or "")[:500],
        })
    return evidence


def _merge_profile(base: ProductProfile, override: ProductProfile | dict[str, Any] | None) -> ProductProfile:
    data = base.model_dump(mode="json")
    if isinstance(override, ProductProfile):
        override_data = override.model_dump(mode="json")
    elif isinstance(override, dict):
        override_data = override
    else:
        override_data = {}

    for key, value in override_data.items():
        if key not in data:
            continue
        if isinstance(value, str) and value.strip():
            data[key] = value.strip()
        elif isinstance(value, list) and value:
            data[key] = [str(item).strip() for item in value if str(item).strip()]

    return ProductProfile(**data)


def _infer_variant_tier(product_name: str) -> str:
    lowered = product_name.lower()
    if "ultra" in lowered:
        return "ultra"
    if "rsr" in lowered:
        return "ultra"
    if "pro max" in lowered or "promax" in lowered:
        return "pro max"
    if "pro" in lowered:
        return "pro"
    if "plus" in lowered or "+" in lowered:
        return "plus"
    if "mini" in lowered:
        return "mini"
    if re.search(r"\bair\b", lowered):
        return "air"
    return "standard"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if match:
        text = match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None
