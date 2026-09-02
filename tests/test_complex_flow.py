import json

import pytest
from openai import APIError

from app.services import complex_flow
from app.services.telecom_client import ToolResult


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeClient:
    """Returns canned responses in call order; one FakeClient per _client() call
    (matching the real `async with _client() as client:` pattern), sharing a
    queue across instances so plan/fetch/answer see it as one sequence.
    """

    def __init__(self, queue, exc=None):
        self._queue = queue
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            if self._outer._exc:
                raise self._outer._exc
            return FakeCompletion(self._outer._queue.pop(0))

    @property
    def chat(self):
        completions = self._Completions(self)
        return type("Chat", (), {"completions": completions})()


def make_client_factory(queue=None, exc=None):
    def factory():
        return FakeClient(queue if queue is not None else [], exc=exc)

    return factory


@pytest.mark.asyncio
async def test_happy_path_plans_fetches_concurrently_and_answers(monkeypatch):
    queue = [
        json.dumps({"tools": ["BALANCE", "OFFERS"]}),
        "You have 76 SMS left and 2 offers you could add on.",
    ]
    monkeypatch.setattr(complex_flow, "_client", make_client_factory(queue))

    captured = {}

    async def fake_execute_tool(intent, customer):
        captured.setdefault("intents", []).append(intent)
        if intent == "BALANCE":
            return ToolResult(success=True, data={"data": {"sms": {"remaining": 76}}})
        return ToolResult(success=True, data={"data": {"offers": [{"name": "A"}, {"name": "B"}]}})

    monkeypatch.setattr(complex_flow, "execute_tool", fake_execute_tool)

    answer, fetched = await complex_flow.run_complex_flow("what are my add-ons", "+919999900003")

    assert answer == "You have 76 SMS left and 2 offers you could add on."
    assert set(captured["intents"]) == {"BALANCE", "OFFERS"}
    assert fetched["BALANCE"] == {"sms": {"remaining": 76}}
    assert fetched["OFFERS"] == {"offers": [{"name": "A"}, {"name": "B"}]}


@pytest.mark.asyncio
async def test_hallucinated_tool_name_is_filtered_before_execute_tool(monkeypatch):
    queue = [
        json.dumps({"tools": ["BALANCE", "DELETE_ACCOUNT", "NOT_A_REAL_TOOL"]}),
        "Here's your balance.",
    ]
    monkeypatch.setattr(complex_flow, "_client", make_client_factory(queue))

    called_with = []

    async def fake_execute_tool(intent, customer):
        called_with.append(intent)
        return ToolResult(success=True, data={"data": {}})

    monkeypatch.setattr(complex_flow, "execute_tool", fake_execute_tool)

    await complex_flow.run_complex_flow("what are my add-ons", "+919999900003")

    assert called_with == ["BALANCE"]


@pytest.mark.asyncio
async def test_planning_failure_yields_empty_plan_and_no_fetch(monkeypatch):
    exc = APIError("boom", request=None, body=None)
    monkeypatch.setattr(complex_flow, "_client", make_client_factory(exc=exc))

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("execute_tool should not be called when planning fails")

    monkeypatch.setattr(complex_flow, "execute_tool", fail_if_called)

    answer, fetched = await complex_flow.run_complex_flow("something odd", "+919999900003")

    assert fetched == {}
    assert answer == complex_flow.FALLBACK_ANSWER


@pytest.mark.asyncio
async def test_partial_tool_failure_marks_error_without_crashing(monkeypatch):
    queue = [
        json.dumps({"tools": ["PROFILE", "DEVICE_DETAILS"]}),
        "Your device isn't fully compatible; profile is fine.",
    ]
    monkeypatch.setattr(complex_flow, "_client", make_client_factory(queue))

    async def fake_execute_tool(intent, customer):
        if intent == "PROFILE":
            return ToolResult(success=True, data={"data": {"status": "Active"}})
        return ToolResult(success=False, error="telecom_api_timeout")

    monkeypatch.setattr(complex_flow, "execute_tool", fake_execute_tool)

    answer, fetched = await complex_flow.run_complex_flow("am I eligible for 5G", "+919999900003")

    assert fetched["PROFILE"] == {"status": "Active"}
    assert fetched["DEVICE_DETAILS"] == {"error": "telecom_api_timeout"}
    assert answer


@pytest.mark.asyncio
async def test_answer_llm_failure_falls_back_gracefully(monkeypatch):
    queue = [json.dumps({"tools": []})]  # plan succeeds with no lookups needed

    call_count = {"n": 0}

    def factory():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return FakeClient(queue)
        return FakeClient([], exc=APIError("answer call failed", request=None, body=None))

    monkeypatch.setattr(complex_flow, "_client", factory)

    answer, fetched = await complex_flow.run_complex_flow("should I get roaming?", "+919999900003")

    assert fetched == {}
    assert answer == complex_flow.FALLBACK_ANSWER


@pytest.mark.asyncio
async def test_empty_plan_skips_fetch_entirely(monkeypatch):
    queue = [json.dumps({"tools": []}), "That's a general question I can answer directly."]
    monkeypatch.setattr(complex_flow, "_client", make_client_factory(queue))

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("execute_tool should not be called for an empty plan")

    monkeypatch.setattr(complex_flow, "execute_tool", fail_if_called)

    answer, fetched = await complex_flow.run_complex_flow("what's roaming?", "+919999900003")

    assert fetched == {}
    assert answer == "That's a general question I can answer directly."
