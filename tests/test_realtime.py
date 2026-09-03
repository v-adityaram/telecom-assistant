import httpx
import pytest

from app.config import get_settings
from app.services import realtime


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json_data


class FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        if self._exc:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_create_realtime_session_success(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(200, {"value": "ephemeral-token-123"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert result.success is True
    assert result.client_secret == "ephemeral-token-123"
    assert result.realtime_url.endswith("/realtime/calls")


@pytest.mark.asyncio
async def test_transcription_is_never_sent_at_mint_time(monkeypatch):
    # Confirmed live: Azure's client_secrets endpoint returns DeploymentNotFound
    # when audio.input.transcription is requested at mint time. Transcription
    # must only be enabled via a post-connect session.update (see voice.py /
    # the frontend), never in this payload, even when a deployment is configured.
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_transcribe_deployment", "gpt-4o-mini-transcribe")

    captured = {}

    class CapturingClient(FakeAsyncClient):
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return await super().post(url, json=json, headers=headers)

    fake_client = CapturingClient(response=FakeResponse(200, {"value": "tok"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert "transcription" not in captured["payload"]["session"]["audio"]["input"]
    assert result.post_connect_update["type"] == "session.update"
    update_session = result.post_connect_update["session"]
    assert update_session["audio"]["input"]["transcription"] == {"model": "gpt-4o-mini-transcribe"}
    # The full session must be re-stated, not just transcription — Azure's
    # session.update replaces nested objects wholesale rather than merging,
    # so a partial update risks silently resetting fields like voice/instructions.
    assert update_session["audio"]["output"] == {"voice": "alloy"}
    assert update_session["instructions"] == realtime.INSTRUCTIONS
    assert update_session["tools"] == realtime.REALTIME_TOOLS
    assert update_session["type"] == "realtime"


@pytest.mark.asyncio
async def test_post_connect_update_is_none_when_transcription_unconfigured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_transcribe_deployment", "")

    fake_client = FakeAsyncClient(response=FakeResponse(200, {"value": "tok"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert result.post_connect_update is None


@pytest.mark.asyncio
async def test_create_realtime_session_missing_value(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(200, {}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert result.success is False
    assert result.error == "realtime_session_invalid_response"


@pytest.mark.asyncio
async def test_create_realtime_session_timeout(monkeypatch):
    fake_client = FakeAsyncClient(exc=httpx.TimeoutException("timeout"))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert result.success is False
    assert result.error == "realtime_session_timeout"


@pytest.mark.asyncio
async def test_create_realtime_session_http_error(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(401))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    assert result.success is False
    assert result.error == "realtime_session_error"


@pytest.mark.asyncio
async def test_noise_reduction_is_sent_at_mint_and_post_connect(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_transcribe_deployment", "gpt-live-transcribe")
    monkeypatch.setattr(settings, "realtime_noise_reduction_mode", "near_field")

    captured = {}

    class CapturingClient(FakeAsyncClient):
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return await super().post(url, json=json, headers=headers)

    fake_client = CapturingClient(response=FakeResponse(200, {"value": "tok"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    mint_input = captured["payload"]["session"]["audio"]["input"]
    update_input = result.post_connect_update["session"]["audio"]["input"]
    assert mint_input["noise_reduction"] == {"type": "near_field"}
    assert update_input["noise_reduction"] == {"type": "near_field"}


@pytest.mark.asyncio
async def test_vad_threshold_is_configurable(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "realtime_vad_threshold", 0.8)

    captured = {}

    class CapturingClient(FakeAsyncClient):
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return await super().post(url, json=json, headers=headers)

    fake_client = CapturingClient(response=FakeResponse(200, {"value": "tok"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    await realtime.create_realtime_session()

    assert captured["payload"]["session"]["audio"]["input"]["turn_detection"]["threshold"] == 0.8


def test_function_name_to_intent_matches_tool_registry():
    from app.tools.registry import TOOL_REGISTRY

    assert set(realtime.FUNCTION_NAME_TO_INTENT.values()) == set(TOOL_REGISTRY.keys())


def test_every_realtime_tool_has_a_mapped_intent():
    tool_names = {tool["name"] for tool in realtime.REALTIME_TOOLS}
    assert tool_names == set(realtime.FUNCTION_NAME_TO_INTENT.keys())


@pytest.mark.asyncio
async def test_server_auto_response_is_off_only_when_transcription_is_on(monkeypatch):
    # With a transcript available the browser triggers each response itself so it
    # can state the caller's language first; without one the server must keep
    # auto-responding or the caller would get silence.
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_transcribe_deployment", "gpt-live-transcribe")

    captured = {}

    class CapturingClient(FakeAsyncClient):
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return await super().post(url, json=json, headers=headers)

    fake_client = CapturingClient(response=FakeResponse(200, {"value": "tok"}))
    monkeypatch.setattr(realtime.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await realtime.create_realtime_session()

    mint_td = captured["payload"]["session"]["audio"]["input"]["turn_detection"]
    update_td = result.post_connect_update["session"]["audio"]["input"]["turn_detection"]
    assert mint_td["create_response"] is True      # no transcript yet at mint time
    assert update_td["create_response"] is False   # browser drives responses once transcription is on
    assert "CURRENT CALLER LANGUAGE" in result.post_connect_update["session"]["instructions"]
