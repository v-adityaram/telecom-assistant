from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult, get_json


async def get_device_details(customer: CustomerContext) -> ToolResult:
    return await get_json("/api/device-details", customer.mobile_number)
