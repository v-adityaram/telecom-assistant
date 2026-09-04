import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_module
from app.main import app
from app.router.schemas import RouterResult
from app.services import session_store
from app.services.telecom_client import ToolResult

client = TestClient(app)

MOBILE_NUMBER = "+919999900003"


@pytest.fixture(autouse=True)
def _no_real_conversation_store(monkeypatch):
    # Cosmos is configured in this repo's local .env for live use — without
    # this, every test here would make real reads/writes against it. Unit
    # tests stay fully offline; conversation-history behavior itself is
    # covered separately, in test_conversation_history below.
    monkeypatch.setattr(chat_module, "_load_history", lambda *a, **k: [])
    monkeypatch.setattr(chat_module, "_persist_turn", lambda *a, **k: None)


def _patch_route_intent(monkeypatch, result: RouterResult):
    async def fake_route_intent(message, candidate_intents=None, history=None):
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
        json={"message": "what's my balance?", "mobile_number": MOBILE_NUMBER},
    )

    _, customer = execute_tool_spy.captured
    assert customer.mobile_number == MOBILE_NUMBER


def test_message_naming_a_different_number_declines_without_router_or_tool_call(monkeypatch):
    # A message stating a different phone number must never silently be
    # answered using the authenticated account's own data framed as if it
    # answered about that other number (misleading) — it must decline
    # up front, before the router or any tool ever runs.
    route_intent_spy = _patch_route_intent(
        monkeypatch,
        RouterResult(intent="DEVICE_DETAILS", confidence=0.98, needs_clarification=False),
    )
    execute_tool_spy = _patch_execute_tool(monkeypatch, ToolResult(success=True, data={"data": {}}))

    response = client.post(
        "/api/chat",
        json={"message": "what's the device of 9999900004", "mobile_number": MOBILE_NUMBER},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "answer"
    assert "signed in with" in body["message"]
    assert not hasattr(route_intent_spy, "captured")
    assert not hasattr(execute_tool_spy, "captured")


def test_message_naming_the_same_number_is_not_treated_as_different(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="DEVICE_DETAILS", confidence=0.98, needs_clarification=False),
    )
    execute_tool_spy = _patch_execute_tool(monkeypatch, ToolResult(success=True, data={"data": {}}))

    response = client.post(
        "/api/chat",
        json={"message": "what's the device of 9999900003", "mobile_number": MOBILE_NUMBER},
    )

    assert response.json()["type"] == "answer"
    assert execute_tool_spy.captured is not None


def test_complex_intent_routes_to_langgraph_fallback(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="COMPLEX", confidence=0.9, needs_clarification=False),
    )

    async def fake_run_complex_flow(message, mobile_number, history=None):
        fake_run_complex_flow.captured = (message, mobile_number, history)
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
    assert fake_run_complex_flow.captured == ("am I eligible for 5G", MOBILE_NUMBER, [])


def test_buy_offer_intent_routes_to_purchase_flow(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BUY_OFFER", confidence=0.9, needs_clarification=False),
    )

    async def fake_run_buy_offer_flow(message, mobile_number, history=None):
        fake_run_buy_offer_flow.captured = (message, mobile_number, history)
        return "I've captured your selection: 6 GB Data Booster (₹70). This is not a real purchase."

    monkeypatch.setattr(chat_module, "run_buy_offer_flow", fake_run_buy_offer_flow)

    response = client.post(
        "/api/chat", json={"message": "buy the 2nd one", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "answer"
    assert body["intent"] == "BUY_OFFER"
    assert "6 GB Data Booster" in body["message"]
    assert fake_run_buy_offer_flow.captured == ("buy the 2nd one", MOBILE_NUMBER, [])


def test_specific_scope_uses_synthesized_answer_not_template(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BALANCE", confidence=0.95, needs_clarification=False, scope="specific"),
    )
    _patch_execute_tool(
        monkeypatch,
        ToolResult(success=True, data={"data": {"sms": {"remaining": 76}}}),
    )

    async def fake_synthesize(message, data):
        fake_synthesize.captured = (message, data)
        return "You have 76 SMS left."

    monkeypatch.setattr(chat_module, "synthesize_specific_answer", fake_synthesize)

    response = client.post("/api/chat", json={"message": "sms", "mobile_number": MOBILE_NUMBER})

    body = response.json()
    assert response.status_code == 200
    assert body["message"] == "You have 76 SMS left."
    assert fake_synthesize.captured == ("sms", {"BALANCE": {"sms": {"remaining": 76}}})


def test_full_scope_still_uses_template(monkeypatch):
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="BALANCE", confidence=0.95, needs_clarification=False, scope="full"),
    )
    _patch_execute_tool(
        monkeypatch,
        ToolResult(success=True, data={"data": {"mainWallet": {"balance": 50, "currency": "INR"}}}),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("synthesize_specific_answer should not be called for full scope")

    monkeypatch.setattr(chat_module, "synthesize_specific_answer", fail_if_called)

    response = client.post("/api/chat", json={"message": "what's my balance", "mobile_number": MOBILE_NUMBER})

    body = response.json()
    assert response.status_code == 200
    assert "Main balance: ₹50" in body["message"]


def test_complex_flow_receives_prior_conversation_history(monkeypatch):
    # F-003: a COMPLEX turn (which is where meta-questions like "what did I
    # ask" land, per the router calibration) must see this conversation's
    # real prior turns, not just the current message in isolation.
    prior_history = [
        {"role": "user", "content": "what's my balance"},
        {"role": "assistant", "content": "Main balance: ₹102.5"},
    ]
    monkeypatch.setattr(chat_module, "_load_history", lambda session_id, mobile_number: prior_history)
    persisted = {}
    monkeypatch.setattr(
        chat_module,
        "_persist_turn",
        lambda session_id, mobile_number, history, user_message, assistant_message: persisted.update(
            session_id=session_id, history=history, user_message=user_message, assistant_message=assistant_message
        ),
    )
    _patch_route_intent(
        monkeypatch,
        RouterResult(intent="COMPLEX", confidence=0.9, needs_clarification=False),
    )

    async def fake_run_complex_flow(message, mobile_number, history=None):
        fake_run_complex_flow.captured_history = history
        return "You asked about your balance a moment ago.", {}

    monkeypatch.setattr(chat_module, "run_complex_flow", fake_run_complex_flow)

    response = client.post(
        "/api/chat", json={"message": "what all did I ask", "mobile_number": MOBILE_NUMBER}
    )

    assert response.status_code == 200
    assert fake_run_complex_flow.captured_history == prior_history
    assert persisted["history"] == prior_history
    assert persisted["user_message"] == "what all did I ask"
    assert persisted["assistant_message"] == "You asked about your balance a moment ago."
