import httpx
import pytest

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


def test_function_name_to_intent_matches_tool_registry():
    from app.tools.registry import TOOL_REGISTRY

    assert set(realtime.FUNCTION_NAME_TO_INTENT.values()) == set(TOOL_REGISTRY.keys())


def test_every_realtime_tool_has_a_mapped_intent():
    tool_names = {tool["name"] for tool in realtime.REALTIME_TOOLS}
    assert tool_names == set(realtime.FUNCTION_NAME_TO_INTENT.keys())
