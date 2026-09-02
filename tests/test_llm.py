import json

import pytest
from openai import APIError, APITimeoutError

from app.services import llm


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    async def create(self, **kwargs):
        self._captured_kwargs = kwargs
        if self._exc:
            raise self._exc
        return FakeCompletion(json.dumps(self._result))


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeAzureClient:
    def __init__(self, result=None, exc=None):
        self.completions = FakeCompletions(result=result, exc=exc)
        self.chat = FakeChat(self.completions)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_classify_intent_returns_parsed_json(monkeypatch):
    expected = {
        "intent": "BALANCE",
        "confidence": 0.97,
        "possible_intents": [],
        "clarification_question": "",
    }
    fake_client = FakeAzureClient(result=expected)
    monkeypatch.setattr(llm, "_client", lambda: fake_client)

    result = await llm.classify_intent("what is my balence")

    assert result == expected


@pytest.mark.asyncio
async def test_classify_intent_includes_candidate_note_in_prompt(monkeypatch):
    fake_client = FakeAzureClient(result={"intent": "OFFERS", "confidence": 0.9})
    monkeypatch.setattr(llm, "_client", lambda: fake_client)

    await llm.classify_intent("the available ones", candidate_intents=["PROFILE", "OFFERS"])

    system_message = fake_client.completions._captured_kwargs["messages"][0]["content"]
    assert "PROFILE, OFFERS" in system_message


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_timeout(monkeypatch):
    fake_client = FakeAzureClient(exc=APITimeoutError(request=None))
    monkeypatch.setattr(llm, "_client", lambda: fake_client)

    result = await llm.classify_intent("what is my balance")

    assert result == llm.FALLBACK_RESULT


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_api_error(monkeypatch):
    fake_client = FakeAzureClient(
        exc=APIError("boom", request=None, body=None),
    )
    monkeypatch.setattr(llm, "_client", lambda: fake_client)

    result = await llm.classify_intent("what is my balance")

    assert result == llm.FALLBACK_RESULT


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_invalid_json(monkeypatch):
    fake_client = FakeAzureClient(result=None)
    fake_client.completions.create = _make_invalid_json_create()
    monkeypatch.setattr(llm, "_client", lambda: fake_client)

    result = await llm.classify_intent("what is my balance")

    assert result == llm.FALLBACK_RESULT


def _make_invalid_json_create():
    async def create(**kwargs):
        return FakeCompletion("not valid json")

    return create
