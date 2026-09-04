from fastapi.testclient import TestClient

from app.api import voice as voice_module
from app.config import get_settings
from app.main import app
from app.services.realtime import RealtimeSessionResult
from app.services.telecom_client import ToolResult

client = TestClient(app)

MOBILE_NUMBER = "+919999900003"


def test_voice_session_returns_client_secret_on_success(monkeypatch):
    async def fake_create_realtime_session():
        return RealtimeSessionResult(
            success=True, client_secret="tok-123", realtime_url="https://example/realtime/calls"
        )

    monkeypatch.setattr(voice_module, "create_realtime_session", fake_create_realtime_session)

    response = client.post("/api/voice/session")

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["client_secret"] == "tok-123"


def test_voice_session_omits_turn_when_unconfigured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "turn_shared_secret", "")

    async def fake_create_realtime_session():
        return RealtimeSessionResult(success=True, client_secret="tok-123")

    monkeypatch.setattr(voice_module, "create_realtime_session", fake_create_realtime_session)

    response = client.post("/api/voice/session")

    assert response.json()["turn"] is None


def test_voice_session_includes_turn_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "turn_shared_secret", "shh")
    monkeypatch.setattr(settings, "turn_domain", "turn.example.com")

    async def fake_create_realtime_session():
        return RealtimeSessionResult(success=True, client_secret="tok-123")

    monkeypatch.setattr(voice_module, "create_realtime_session", fake_create_realtime_session)

    response = client.post("/api/voice/session")

    turn = response.json()["turn"]
    assert turn["urls"] == ["turns:turn.example.com:5349?transport=tcp"]
    assert turn["username"] and turn["credential"]


def test_voice_session_surfaces_failure(monkeypatch):
    async def fake_create_realtime_session():
        return RealtimeSessionResult(success=False, error="realtime_session_timeout")

    monkeypatch.setattr(voice_module, "create_realtime_session", fake_create_realtime_session)

    response = client.post("/api/voice/session")

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["error"] == "realtime_session_timeout"


def test_voice_tool_dispatches_known_function(monkeypatch):
    async def fake_execute_tool(intent, customer):
        fake_execute_tool.captured = (intent, customer)
        return ToolResult(success=True, data={"data": {"mainWallet": {"balance": 50}}})

    monkeypatch.setattr(voice_module, "execute_tool", fake_execute_tool)

    response = client.post(
        "/api/voice/tool", json={"function_name": "get_balance", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"] == {"mainWallet": {"balance": 50}}
    assert fake_execute_tool.captured[0] == "BALANCE"
    assert fake_execute_tool.captured[1].mobile_number == MOBILE_NUMBER


def test_voice_tool_rejects_unknown_function(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("execute_tool should not be called for an unknown function")

    monkeypatch.setattr(voice_module, "execute_tool", fail_if_called)

    response = client.post(
        "/api/voice/tool", json={"function_name": "delete_account", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["error"] == "unknown_function"


def test_voice_tool_surfaces_tool_failure(monkeypatch):
    async def fake_execute_tool(intent, customer):
        return ToolResult(success=False, error="telecom_api_timeout")

    monkeypatch.setattr(voice_module, "execute_tool", fake_execute_tool)

    response = client.post(
        "/api/voice/tool", json={"function_name": "get_offers", "mobile_number": MOBILE_NUMBER}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["error"] == "telecom_api_timeout"
