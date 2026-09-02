from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult, get_json


async def get_purchase_history(customer: CustomerContext) -> ToolResult:
    return await get_json("/api/purchase-history", customer.mobile_number)
