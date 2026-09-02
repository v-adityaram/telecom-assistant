from fastapi.testclient import TestClient

from app.api import chat as chat_module
from app.main import app
from app.router.schemas import RouterResult
from app.services import session_store
from app.services.telecom_client import ToolResult

client = TestClient(app)

MOBILE_NUMBER = "+919999900003"


def _patch_route_intent(monkeypatch, result: RouterResult):
    async def fake_route_intent(message, candidate_intents=None):
        fake_route_intent.captured = (message, candidate_intents)
        return result

    monkeypatch.setattr(chat_module, "route_intent", fake_route_intent)
    return fake_route_intent


def _patch_execute_tool(monkeypatch, tool_result: ToolResult):
    async def fake_execute_tool(intent, customer):
        fake_execute_tool.captured = (intent, customer)
        return tool_result

    monkeypatch.setattr(chat_module, "execute_tool", fake_execute_tool)
    return fake_execute_tool


def test_high_confidence_intent_returns_answer(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BALANCE", confidence=0.98, needs_clarification=False),
    )
    _patch_execute_tool(
        monkeypatch,
        ToolResult(success=True, data={"data": {"mainWallet": {"balance": 100, "currency": "INR"}}}),
    )

    response = client.post(
        "/api/chat", json={"message": "what is my balence", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "answer"
    assert body["intent"] == "BALANCE"
    assert "Main balance: ₹100" in body["message"]
    assert body["session_id"]


def test_low_confidence_intent_returns_clarification_without_calling_tool(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(
            intent=None,
            confidence=0.5,
            needs_clarification=True,
            possible_intents=["PROFILE", "OFFERS"],
            clarification_message="Do you mean your current plan or available plans?",
        ),
    )
    execute_tool_spy = _patch_execute_tool(monkeypatch, ToolResult(success=True, data={}))

    response = client.post("/api/chat", json={"message": "check my plan", "mobile_number": MOBILE_NUMBER})

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "clarification"
    assert body["message"] == "Do you mean your current plan or available plans?"
    assert body["possible_intents"] == ["PROFILE", "OFFERS"]
    assert body["intent"] is None
    assert not hasattr(execute_tool_spy, "captured")


def test_clarification_stores_pending_state_for_session(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(
            intent=None,
            confidence=0.5,
            needs_clarification=True,
            possible_intents=["PROFILE", "OFFERS"],
            clarification_message="Do you mean your current plan or available plans?",
        ),
    )

    response = client.post(
        "/api/chat",
        json={"message": "check my plan", "mobile_number": MOBILE_NUMBER, "session_id": "sess-1"},
    )

    assert response.json()["session_id"] == "sess-1"
    pending = session_store.get_pending("sess-1")
    assert pending.possible_intents == ["PROFILE", "OFFERS"]
    session_store.clear_pending("sess-1")


def test_followup_uses_pending_candidates_and_clears_state(monkeypatch):
    session_store.set_pending(
        "sess-2",
        session_store.PendingClarification(original_message="check my plan", possible_intents=["PROFILE", "OFFERS"]),
    )
    fake_route_intent = _patch_route_intent(
        monkeypatch,
        RouterResult(intent="OFFERS", confidence=0.95, needs_clarification=False),
    )
    _patch_execute_tool(monkeypatch, ToolResult(success=True, data={"data": {"offers": []}}))

    response = client.post(
        "/api/chat",
        json={"message": "the available ones", "mobile_number": MOBILE_NUMBER, "session_id": "sess-2"},
    )

    assert response.json()["type"] == "answer"
    assert fake_route_intent.captured == ("the available ones", ["PROFILE", "OFFERS"])
    assert session_store.get_pending("sess-2") is None


def test_tool_failure_returns_error_type_not_500(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BALANCE", confidence=0.98, needs_clarification=False),
    )
    _patch_execute_tool(monkeypatch, ToolResult(success=False, error="telecom_api_timeout"))

    response = client.post("/api/chat", json={"message": "balance please", "mobile_number": MOBILE_NUMBER})

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "error"
    assert body["intent"] == "BALANCE"


def test_mobile_number_never_sourced_from_message(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BALANCE", confidence=0.98, needs_clarification=False),
    )
    execute_tool_spy = _patch_execute_tool(monkeypatch, ToolResult(success=True, data={"data": {}}))

    client.post(
        "/api/chat",
        json={"message": "my number is +910000000000, what's my balance?", "mobile_number": MOBILE_NUMBER},
    )

    _, customer = execute_tool_spy.captured
    assert customer.mobile_number == MOBILE_NUMBER


def test_complex_intent_routes_to_langgraph_fallback(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="COMPLEX", confidence=0.9, needs_clarification=False),
    )

    async def fake_run_complex_flow(message, mobile_number):
        fake_run_complex_flow.captured = (message, mobile_number)
        return "You're eligible for 5G on both your plan and device.", {"PROFILE": {}, "DEVICE_DETAILS": {}}

    monkeypatch.setattr(chat_module, "run_complex_flow", fake_run_complex_flow)

    response = client.post(
        "/api/chat", json={"message": "am I eligible for 5G", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "answer"
    assert body["intent"] == "COMPLEX"
    assert body["message"] == "You're eligible for 5G on both your plan and device."
    assert body["data"] == {"PROFILE": {}, "DEVICE_DETAILS": {}}
    assert fake_run_complex_flow.captured == ("am I eligible for 5G", MOBILE_NUMBER)
