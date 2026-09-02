import pytest

from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult
from app.tools import balance, device, offers, profile, purchase_history

CUSTOMER = CustomerContext(mobile_number="+919999900003")

CASES = [
    (profile.get_profile, "/api/profile"),
    (device.get_device_details, "/api/device-details"),
    (balance.get_balance, "/api/balance"),
    (purchase_history.get_purchase_history, "/api/purchase-history"),
    (offers.get_offers, "/api/offers"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_fn,expected_path", CASES)
async def test_tool_calls_expected_path(monkeypatch, tool_fn, expected_path):
    captured = {}

    async def fake_get_json(path, mobile_number):
        captured["path"] = path
        captured["mobile_number"] = mobile_number
        return ToolResult(success=True, data={"ok": True})

    monkeypatch.setattr(f"{tool_fn.__module__}.get_json", fake_get_json)

    result = await tool_fn(CUSTOMER)

    assert captured["path"] == expected_path
    assert captured["mobile_number"] == "+919999900003"
    assert result.success is True
