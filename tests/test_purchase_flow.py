import json

import pytest
from openai import APIError

from app.services import purchase_flow
from app.services.telecom_client import ToolResult

OFFERS_DATA = {
    "data": {
        "currency": "INR",
        "offers": [
            {"id": "OFFER-A", "name": "Unlimited Value 239", "price": 248.0},
            {"id": "OFFER-B", "name": "6 GB Data Booster", "price": 70.0},
        ],
    }
}


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
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.captured_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.captured_kwargs = kwargs
            if self._outer._exc:
                raise self._outer._exc
            return FakeCompletion(json.dumps(self._outer._result))

    @property
    def chat(self):
        completions = self._Completions(self)
        return type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_matched_offer_returns_deterministic_grounded_message(monkeypatch):
    async def fake_execute_tool(intent, customer):
        assert intent == "OFFERS"
        return ToolResult(success=True, data=OFFERS_DATA)

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)
    fake_client = FakeClient(result={"matched_offer_id": "OFFER-B"})
    monkeypatch.setattr(purchase_flow, "_client", lambda: fake_client)

    answer = await purchase_flow.run_buy_offer_flow("buy the 2nd one", "+919999900003", history=[])

    assert "6 GB Data Booster" in answer
    assert "70" in answer
    assert purchase_flow.DUMMY_PAYMENT_LINK in answer
    assert "not a real purchase" in answer


@pytest.mark.asyncio
async def test_history_is_sent_to_the_match_call(monkeypatch):
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=True, data=OFFERS_DATA)

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)
    fake_client = FakeClient(result={"matched_offer_id": "OFFER-B"})
    monkeypatch.setattr(purchase_flow, "_client", lambda: fake_client)

    history = [{"role": "user", "content": "what offers do I have"}, {"role": "assistant", "content": "1. ... 2. 6 GB Data Booster"}]
    await purchase_flow.run_buy_offer_flow("buy the 2nd one", "+919999900003", history=history)

    messages = fake_client.captured_kwargs["messages"]
    assert messages[1:3] == history
    assert messages[3] == {"role": "user", "content": "buy the 2nd one"}


@pytest.mark.asyncio
async def test_no_match_returns_clarify_message(monkeypatch):
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=True, data=OFFERS_DATA)

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)
    fake_client = FakeClient(result={"matched_offer_id": None})
    monkeypatch.setattr(purchase_flow, "_client", lambda: fake_client)

    answer = await purchase_flow.run_buy_offer_flow("buy something", "+919999900003", history=[])

    assert answer == purchase_flow.CLARIFY_MESSAGE


@pytest.mark.asyncio
async def test_match_call_failure_falls_back_to_clarify(monkeypatch):
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=True, data=OFFERS_DATA)

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)
    fake_client = FakeClient(exc=APIError("boom", request=None, body=None))
    monkeypatch.setattr(purchase_flow, "_client", lambda: fake_client)

    answer = await purchase_flow.run_buy_offer_flow("buy the 2nd one", "+919999900003", history=[])

    assert answer == purchase_flow.CLARIFY_MESSAGE


@pytest.mark.asyncio
async def test_offers_fetch_failure_does_not_call_the_model(monkeypatch):
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=False, error="telecom_api_timeout")

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)

    def fail_if_called():
        raise AssertionError("_client should not be called when the offers fetch fails")

    monkeypatch.setattr(purchase_flow, "_client", fail_if_called)

    answer = await purchase_flow.run_buy_offer_flow("buy the 2nd one", "+919999900003", history=[])

    assert answer == purchase_flow.FETCH_FAILED_MESSAGE


@pytest.mark.asyncio
async def test_hallucinated_offer_id_is_rejected(monkeypatch):
    # The match call returned an id that doesn't exist in the real offers —
    # must not be trusted; falls back to asking for clarification.
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=True, data=OFFERS_DATA)

    monkeypatch.setattr(purchase_flow, "execute_tool", fake_execute_tool)
    fake_client = FakeClient(result={"matched_offer_id": "NOT-A-REAL-OFFER"})
    monkeypatch.setattr(purchase_flow, "_client", lambda: fake_client)

    answer = await purchase_flow.run_buy_offer_flow("buy the 2nd one", "+919999900003", history=[])

    assert answer == purchase_flow.CLARIFY_MESSAGE
