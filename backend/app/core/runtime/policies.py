from __future__ import annotations

from app.core.runtime.template import ControlDecision, NodeSpec, PauseRequest


class DefaultRoutePolicy:
    def decide(self, state: dict, spec: NodeSpec) -> ControlDecision:
        if spec.default_next == "done":
            return ControlDecision(action="finish", reason="default terminal route")
        return ControlDecision(action="continue", next_node=spec.default_next)


class ReviewFailPausePolicy:
    def build_pause(self, state: dict, spec: NodeSpec) -> PauseRequest | None:
        data = state.get("data") or {}
        control = state.get("control") or {}
        review = data.get("review_result")
        if not isinstance(review, dict) or review.get("passed") is not False:
            return None

        revision_count = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        max_revisions = int(control.get("max_revisions", data.get("max_revisions", 3)) or 3)
        if revision_count >= max_revisions:
            return None

        target = review.get("target_node") if review.get("target_node") in spec.allowed_routes else "analysis"
        reason = review.get("feedback") or f"报告评分 {review.get('score', 0)}，未通过质检"
        return PauseRequest(
            node_id=spec.id,
            reason=reason,
            suggested_route=target,
            options=[
                {"value": "jump", "label": "按建议重试", "target_node": target},
                {"value": "approve", "label": "强制通过（接受当前报告）"},
                {"value": "abort", "label": "放弃本次分析"},
            ],
            context={
                "score": review.get("score"),
                "checks": review.get("checks", []),
                "specific_issues": review.get("specific_issues", []),
                "target_node": target,
            },
        )


class ReviewRoutePolicy:
    def decide(self, state: dict, spec: NodeSpec) -> ControlDecision:
        data = state.get("data") or {}
        control = state.get("control") or {}
        review = data.get("review_result")
        if not isinstance(review, dict):
            return ControlDecision(action="fail", reason="review node did not produce review_result")

        if review.get("passed") is True:
            return ControlDecision(action="finish", reason="review passed")

        revision_count = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        max_revisions = int(control.get("max_revisions", data.get("max_revisions", 3)) or 3)
        if revision_count >= max_revisions:
            return ControlDecision(action="fail", reason=review.get("feedback") or "review failed at max revisions")

        human_decision = control.get("human_decision") or {}
        target = None
        if human_decision.get("action") == "jump":
            target = human_decision.get("target_node")
        if target not in spec.allowed_routes:
            target = review.get("target_node")
        if target not in spec.allowed_routes:
            target = "analysis"
        return ControlDecision(action="route", next_node=target, reason="review failed reroute")
