import pytest

from app.services.interview_service import (
    CONFIG_COMPLETE_FALLBACK,
    CONFIG_UPDATED_FALLBACK,
    EMPTY_RESPONSE_FALLBACK,
    _clean_interview_response,
    _collect_interview_response,
)


class FakeInterviewAgent:
    def __init__(self, responses: list[list[str]]):
        self.responses = responses
        self.calls = 0

    async def stream_response(self, _messages):
        response = self.responses[self.calls]
        self.calls += 1
        for chunk in response:
            yield chunk


@pytest.mark.asyncio
async def test_collect_interview_response_retries_empty_response():
    agent = FakeInterviewAgent([[], ["有效", "回复"]])

    response = await _collect_interview_response([], lambda: agent)

    assert response == "有效回复"
    assert agent.calls == 2


@pytest.mark.asyncio
async def test_collect_interview_response_falls_back_after_two_empty_responses():
    agent = FakeInterviewAgent([[], []])

    response = await _collect_interview_response([], lambda: agent)

    assert response == EMPTY_RESPONSE_FALLBACK
    assert agent.calls == 2


def test_clean_interview_response_keeps_text_around_config():
    response = "请确认以下配置。\n```json\n{\"target_product\": \"示例\"}\n```\n确认后即可开始。"

    cleaned = _clean_interview_response(response, has_config=True, is_complete=False)

    assert cleaned == "请确认以下配置。\n\n确认后即可开始。"


def test_clean_interview_response_falls_back_when_final_reply_only_contains_config():
    response = '```json\n{"target_product": "示例"}\n```\n---CONFIG_COMPLETE---'

    cleaned = _clean_interview_response(response, has_config=True, is_complete=True)

    assert cleaned == CONFIG_COMPLETE_FALLBACK


def test_clean_interview_response_falls_back_when_draft_reply_only_contains_config():
    response = '```json\n{"target_product": "示例"}\n```'

    cleaned = _clean_interview_response(response, has_config=True, is_complete=False)

    assert cleaned == CONFIG_UPDATED_FALLBACK
