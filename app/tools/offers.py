from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult, get_json


async def get_offers(customer: CustomerContext) -> ToolResult:
    return await get_json("/api/offers", customer.mobile_number)
