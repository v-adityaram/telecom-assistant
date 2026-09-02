import pytest
from openai import APIError

from app.services import answer_synthesis


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
    def __init__(self, content=None, exc=None):
        self._content = content
        self._exc = exc

    async def create(self, **kwargs):
        self._captured_kwargs = kwargs
        if self._exc:
            raise self._exc
        return FakeCompletion(self._content)


class FakeClient:
    def __init__(self, content=None, exc=None):
        self.completions = FakeCompletions(content=content, exc=exc)
        self.chat = type("Chat", (), {"completions": self.completions})()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_synthesize_specific_answer_returns_model_text(monkeypatch):
    fake_client = FakeClient(content="You have 76 SMS left.")
    monkeypatch.setattr(answer_synthesis, "_client", lambda: fake_client)

    answer = await answer_synthesis.synthesize_specific_answer("sms", {"BALANCE": {"sms": {"remaining": 76}}})

    assert answer == "You have 76 SMS left."


@pytest.mark.asyncio
async def test_synthesize_specific_answer_includes_data_and_question_in_prompt(monkeypatch):
    fake_client = FakeClient(content="Yes, it supports 5G.")
    monkeypatch.setattr(answer_synthesis, "_client", lambda: fake_client)

    await answer_synthesis.synthesize_specific_answer(
        "is my phone 5g", {"DEVICE_DETAILS": {"device": {"networkCapability": ["5G"]}}}
    )

    prompt = fake_client.completions._captured_kwargs["messages"][0]["content"]
    assert "is my phone 5g" in prompt
    assert "networkCapability" in prompt


@pytest.mark.asyncio
async def test_synthesize_specific_answer_falls_back_on_timeout(monkeypatch):
    fake_client = FakeClient(exc=TimeoutError())
    monkeypatch.setattr(answer_synthesis, "_client", lambda: fake_client)

    answer = await answer_synthesis.synthesize_specific_answer("sms", {"BALANCE": {}})

    assert answer == answer_synthesis.FALLBACK_ANSWER


@pytest.mark.asyncio
async def test_synthesize_specific_answer_falls_back_on_api_error(monkeypatch):
    fake_client = FakeClient(exc=APIError("boom", request=None, body=None))
    monkeypatch.setattr(answer_synthesis, "_client", lambda: fake_client)

    answer = await answer_synthesis.synthesize_specific_answer("sms", {"BALANCE": {}})

    assert answer == answer_synthesis.FALLBACK_ANSWER
