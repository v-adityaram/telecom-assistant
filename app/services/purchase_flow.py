"""Demo "buy an offer" flow for the BUY_OFFER intent. Never a real purchase —
matches a customer's request (which may only make sense in light of an
earlier offers listing, e.g. "buy the 2nd one") against their real,
freshly-fetched offers, then returns a deterministic, data-grounded
confirmation with a disclosed dummy payment link. The LLM only ever picks
*which* real offer is meant (structured output); the final message itself is
built from that offer's real fields, never freeform LLM text, so a price or
name can never be invented.
"""

import asyncio
import json
import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.config import get_settings
from app.services.customer_context import get_customer_context
from app.services.response import _money
from app.tools.registry import execute_tool

logger = logging.getLogger("telecom_assistant.purchase_flow")

TIMEOUT_SECONDS = 6.0
DUMMY_PAYMENT_LINK = "https://dummy-payment-link.example"

MATCH_PROMPT = """You are matching a telecom customer's purchase request to
one specific offer from their real, currently available offers.

The customer's conversation history is given to you as prior turns — use it
to resolve references like "the 2nd one", "that data booster", or an ordinal
position, matching against whatever offers list was shown earlier in the
conversation. If the current message already names the offer clearly enough
on its own, use that instead.

Available offers right now (JSON list of {{id, name, price}}):
{offers_json}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"matched_offer_id": "<one of the ids above, or null if you genuinely can't tell which offer they mean>"}}"""

CLARIFY_MESSAGE = (
    'Which offer would you like to buy? You can name it, or say something like '
    '"the 2nd one" from the list I showed you.'
)

FETCH_FAILED_MESSAGE = "I couldn't load your offers right now — please try again shortly."


def _client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(base_url=settings.azure_openai_endpoint, api_key=settings.azure_openai_api_key)


async def _match_offer_id(message: str, offers: list[dict], history: list[dict]) -> str | None:
    settings = get_settings()
    offers_for_match = [{"id": o.get("id"), "name": o.get("name"), "price": o.get("price")} for o in offers]
    prompt = MATCH_PROMPT.format(offers_json=json.dumps(offers_for_match))
    messages = [{"role": "system", "content": prompt}]
    messages.extend((history or [])[-20:])
    messages.append({"role": "user", "content": message})

    try:
        async with _client() as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.azure_openai_deployment,
                    messages=messages,
                    reasoning_effort="minimal",
                    max_completion_tokens=100,
                    response_format={"type": "json_object"},
                ),
                timeout=TIMEOUT_SECONDS,
            )
        raw = json.loads(response.choices[0].message.content)
        return raw.get("matched_offer_id")
    except (TimeoutError, APITimeoutError, APIError, ValueError, KeyError):
        logger.warning("purchase_flow_match_failed")
        return None


async def run_buy_offer_flow(message: str, mobile_number: str, history: list[dict] | None = None) -> str:
    """Returns the assistant's reply text. Never calls a real payment API —
    a disclosed demo flow only, same as the reference design it follows."""
    customer = get_customer_context(mobile_number)
    tool_result = await execute_tool("OFFERS", customer)
    if not tool_result.success:
        return FETCH_FAILED_MESSAGE

    offer_data = (tool_result.data or {}).get("data") or {}
    offers = offer_data.get("offers") or []
    if not offers:
        return "You don't have any offers available to buy right now."

    matched_id = await _match_offer_id(message, offers, history or [])
    matched = next((o for o in offers if o.get("id") == matched_id), None)
    if not matched:
        return CLARIFY_MESSAGE

    price = _money(matched.get("price"), offer_data.get("currency"))
    return (
        f"I've captured your selection: {matched.get('name')} ({price}). "
        f"This is not a real purchase. Please use this dummy payment link to "
        f"continue: {DUMMY_PAYMENT_LINK}"
    )
