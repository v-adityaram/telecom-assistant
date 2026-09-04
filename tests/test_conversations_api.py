from fastapi.testclient import TestClient

from app.api import conversations as conversations_module
from app.main import app

client = TestClient(app)

MOBILE_NUMBER = "+919999900003"


def test_list_conversations_returns_summaries(monkeypatch):
    def fake_list_conversations(mobile_number):
        assert mobile_number == MOBILE_NUMBER
        return [
            {"id": "conv-1", "title": "What's my balance?", "updatedAt": "2026-09-04T10:00:00"},
            {"id": "conv-2", "title": None, "updatedAt": "2026-09-04T09:00:00"},
        ]

    monkeypatch.setattr(conversations_module.conversation_store, "list_conversations", fake_list_conversations)

    response = client.get("/api/conversations", params={"mobile_number": MOBILE_NUMBER})

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {"id": "conv-1", "title": "What's my balance?", "updated_at": "2026-09-04T10:00:00"},
        {"id": "conv-2", "title": "New conversation", "updated_at": "2026-09-04T09:00:00"},
    ]


def test_get_conversation_returns_messages(monkeypatch):
    def fake_get_conversation(conversation_id, mobile_number):
        assert conversation_id == "conv-1"
        assert mobile_number == MOBILE_NUMBER
        return {
            "id": "conv-1",
            "mobileNumber": mobile_number,
            "messages": [
                {"role": "user", "content": "what's my balance"},
                {"role": "assistant", "content": "Main balance: ₹102.5"},
            ],
        }

    monkeypatch.setattr(conversations_module.conversation_store, "get_conversation", fake_get_conversation)

    response = client.get("/api/conversations/conv-1", params={"mobile_number": MOBILE_NUMBER})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "conv-1"
    assert body["messages"] == [
        {"role": "user", "content": "what's my balance"},
        {"role": "assistant", "content": "Main balance: ₹102.5"},
    ]


def test_get_missing_conversation_returns_404(monkeypatch):
    monkeypatch.setattr(conversations_module.conversation_store, "get_conversation", lambda cid, mobile: None)

    response = client.get("/api/conversations/does-not-exist", params={"mobile_number": MOBILE_NUMBER})

    assert response.status_code == 404


def test_missing_mobile_number_is_a_validation_error():
    response = client.get("/api/conversations")

    assert response.status_code == 422


def test_append_turn_to_new_conversation(monkeypatch):
    monkeypatch.setattr(conversations_module.conversation_store, "get_conversation", lambda cid, mobile: None)
    captured = {}

    def fake_upsert(conversation_id, mobile_number, messages):
        captured["args"] = (conversation_id, mobile_number, messages)

    monkeypatch.setattr(conversations_module.conversation_store, "upsert_conversation", fake_upsert)

    response = client.post(
        "/api/conversations/voice-conv-1/turns",
        json={"mobile_number": MOBILE_NUMBER, "user_message": "what's my balance", "assistant_message": "₹102.5"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert captured["args"] == (
        "voice-conv-1",
        MOBILE_NUMBER,
        [
            {"role": "user", "content": "what's my balance"},
            {"role": "assistant", "content": "₹102.5"},
        ],
    )


def test_append_turn_extends_existing_conversation(monkeypatch):
    existing = [
        {"role": "user", "content": "show my device"},
        {"role": "assistant", "content": "OnePlus Nord CE 4"},
    ]
    monkeypatch.setattr(
        conversations_module.conversation_store, "get_conversation", lambda cid, mobile: {"messages": existing}
    )
    captured = {}
    monkeypatch.setattr(
        conversations_module.conversation_store,
        "upsert_conversation",
        lambda cid, mobile, messages: captured.setdefault("messages", messages),
    )

    response = client.post(
        "/api/conversations/voice-conv-1/turns",
        json={"mobile_number": MOBILE_NUMBER, "user_message": "and offers?", "assistant_message": "4 offers available"},
    )

    assert response.status_code == 200
    assert captured["messages"] == existing + [
        {"role": "user", "content": "and offers?"},
        {"role": "assistant", "content": "4 offers available"},
    ]
