from collections.abc import Awaitable, Callable

from app.services.customer_context import CustomerContext
from app.services.telecom_client import ToolResult
from app.tools.balance import get_balance
from app.tools.device import get_device_details
from app.tools.offers import get_offers
from app.tools.profile import get_profile
from app.tools.purchase_history import get_purchase_history

ToolFn = Callable[[CustomerContext], Awaitable[ToolResult]]

# The only way an intent reaches a telecom API call. The router (Phase 4)
# produces an intent string, never a URL/function/arbitrary parameters, and
# this is the single place that maps intent -> tool call.
TOOL_REGISTRY: dict[str, ToolFn] = {
    "PROFILE": get_profile,
    "DEVICE_DETAILS": get_device_details,
    "BALANCE": get_balance,
    "PURCHASE_HISTORY": get_purchase_history,
    "OFFERS": get_offers,
}


class UnknownIntentError(ValueError):
    """Raised when an intent has no allow-listed tool (e.g. UNKNOWN)."""


async def execute_tool(intent: str, customer: CustomerContext) -> ToolResult:
    tool_fn = TOOL_REGISTRY.get(intent)
    if tool_fn is None:
        raise UnknownIntentError(intent)
    return await tool_fn(customer)
