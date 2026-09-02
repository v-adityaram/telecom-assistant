import pytest

from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult
from app.tools.registry import TOOL_REGISTRY, UnknownIntentError, execute_tool

CUSTOMER = CustomerContext(mobile_number="+919999900003")

EXPECTED_PATHS = {
    "PROFILE": "/api/profile",
    "DEVICE_DETAILS": "/api/device-details",
    "BALANCE": "/api/balance",
    "PURCHASE_HISTORY": "/api/purchase-history",
    "OFFERS": "/api/offers",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", TOOL_REGISTRY.keys())
async def test_execute_tool_dispatches_allow_listed_intent(monkeypatch, intent):
    captured = {}

    async def fake_get_json(path, mobile_number):
        captured["path"] = path
        captured["mobile_number"] = mobile_number
        return ToolResult(success=True, data={"ok": True})

    tool_fn = TOOL_REGISTRY[intent]
    monkeypatch.setattr(f"{tool_fn.__module__}.get_json", fake_get_json)

    result = await execute_tool(intent, CUSTOMER)

    assert captured["path"] == EXPECTED_PATHS[intent]
    assert captured["mobile_number"] == "+919999900003"
    assert result.success is True


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_intent():
    with pytest.raises(UnknownIntentError):
        await execute_tool("UNKNOWN", CUSTOMER)


@pytest.mark.asyncio
async def test_execute_tool_rejects_arbitrary_string():
    with pytest.raises(UnknownIntentError):
        await execute_tool("http://evil.example/steal", CUSTOMER)
