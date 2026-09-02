import httpx
import pytest

from app.services import telecom_client


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data or {}
        self._raise_json_error = raise_json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        if self._raise_json_error:
            raise ValueError("invalid json")
        return self._json_data


class FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        if self._exc:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_get_json_success(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(200, {"plan": "gold"}))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is True
    assert result.data == {"plan": "gold"}
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_get_json_timeout(monkeypatch):
    fake_client = FakeAsyncClient(exc=httpx.TimeoutException("timeout"))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is False
    assert result.error == "telecom_api_timeout"


@pytest.mark.asyncio
async def test_get_json_4xx(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(404))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is False
    assert result.error == "telecom_api_error"
    assert result.status_code == 404


@pytest.mark.asyncio
async def test_get_json_5xx(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(500))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is False
    assert result.error == "telecom_api_error"
    assert result.status_code == 500


@pytest.mark.asyncio
async def test_get_json_request_error(monkeypatch):
    fake_client = FakeAsyncClient(exc=httpx.ConnectError("boom"))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is False
    assert result.error == "telecom_api_unreachable"


@pytest.mark.asyncio
async def test_get_json_invalid_response(monkeypatch):
    fake_client = FakeAsyncClient(response=FakeResponse(200, raise_json_error=True))
    monkeypatch.setattr(telecom_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    result = await telecom_client.get_json("/api/balance", "+919999900003")

    assert result.success is False
    assert result.error == "telecom_api_invalid_response"
