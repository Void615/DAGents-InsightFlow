"""Workflow graph orchestration facade.

The old closure-based graph builder was replaced by the reusable runtime
template layer. Keep this module as a small facade so callers have one obvious
place to get the active template.
"""

from app.core.competitive_template import CompetitiveAnalysisTemplate


def get_workflow_template():
    return CompetitiveAnalysisTemplate


__all__ = ["get_workflow_template", "CompetitiveAnalysisTemplate"]
