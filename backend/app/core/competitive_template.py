from __future__ import annotations

from app.agents.analysis_agent import AnalysisAgent
from app.agents.collection_agent import CollectionAgent
from app.agents.report_agent import ReportAgent
from app.agents.review_agent import ReviewAgent
from app.core.runtime.policies import DefaultRoutePolicy, ReviewFailPausePolicy, ReviewRoutePolicy
from app.core.runtime.template import ArtifactDraft, GraphTemplate, NodeSpec, RetryPolicy

REROUTE_TARGETS = ("information_collection", "analysis", "report_writing")

_collection_agent = CollectionAgent()
_analysis_agent = AnalysisAgent()
_report_agent = ReportAgent()
_review_agent = ReviewAgent()


def _collection_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    raw_data = patch.get("raw_data")
    if not raw_data:
        return []
    return [
        ArtifactDraft(
            artifact_type="collection_raw",
            title="采集原始数据",
            content=raw_data,
            created_by_node="information_collection",
        )
    ]


def _analysis_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}
    target = config.get("target_product", "")
    artifacts: list[ArtifactDraft] = []
    for artifact_type, key in [
        ("feature_matrix", "feature_matrix"),
        ("pricing_comparison", "pricing_comparison"),
        ("user_sentiment", "user_sentiment"),
        ("swot_analysis", "swot"),
    ]:
        content = patch.get(key)
        if content is not None:
            artifacts.append(
                ArtifactDraft(
                    artifact_type=artifact_type,
                    title=f"{target} {artifact_type}",
                    content=content,
                    created_by_node="analysis",
                )
            )
    return artifacts


def _report_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    report = patch.get("report")
    if not report:
        return []
    title = report.get("title", "竞品分析报告") if isinstance(report, dict) else "竞品分析报告"
    markdown = report.get("full_markdown", "") if isinstance(report, dict) else ""
    return [
        ArtifactDraft(
            artifact_type="report",
            title=title,
            content=report,
            content_text=markdown,
            created_by_node="report_writing",
        )
    ]


CompetitiveAnalysisTemplate = GraphTemplate(
    name="competitive_analysis",
    entrypoint="information_collection",
    nodes=(
        NodeSpec(
            id="information_collection",
            agent=_collection_agent,
            default_next="analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_collection_artifacts,
        ),
        NodeSpec(
            id="analysis",
            agent=_analysis_agent,
            default_next="report_writing",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_analysis_artifacts,
        ),
        NodeSpec(
            id="report_writing",
            agent=_report_agent,
            default_next="review",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_report_artifacts,
        ),
        NodeSpec(
            id="review",
            agent=_review_agent,
            default_next="done",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            pause_policy=ReviewFailPausePolicy(),
            route_policy=ReviewRoutePolicy(),
        ),
    ),
)
