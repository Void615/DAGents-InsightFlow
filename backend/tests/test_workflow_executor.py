from app.core.workflow_executor import (
    _extract_interrupt_payload,
    _make_pause_state,
    _review_failed,
    _review_failure_message,
)


class DummyInterrupt:
    def __init__(self, value):
        self.value = value


def test_extract_interrupt_payload_from_langgraph_state():
    payload = {
        "paused_by_node": "review",
        "pause_reason": "needs collection",
        "pause_context": {"score": 35},
    }

    assert _extract_interrupt_payload({"__interrupt__": [DummyInterrupt(payload)]}) == payload


def test_review_failed_gate_detects_failed_review():
    state = {
        "review_result": {
            "passed": False,
            "feedback": "竞品来源不足",
            "target_node": "information_collection",
        }
    }

    assert _review_failed(state) is True
    assert _review_failure_message(state) == "竞品来源不足"


def test_review_failed_gate_allows_passed_review():
    assert _review_failed({"review_result": {"passed": True}}) is False
    assert _review_failed({"report": {"title": "ok"}}) is False


def test_make_pause_state_keeps_dag_state_for_resume():
    pause_state = _make_pause_state({
        "paused_by_node": "review",
        "pause_reason": "bad competitors",
        "pause_options": [{"value": "jump"}],
        "pause_context": {"target_node": "information_collection"},
        "dag_state": {"review_result": {"passed": False}},
    })

    assert pause_state["paused_by_node"] == "review"
    assert pause_state["dag_state"]["review_result"]["passed"] is False
    assert "paused_at" in pause_state
