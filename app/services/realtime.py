import logging

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.tools.registry import TOOL_REGISTRY

logger = logging.getLogger("telecom_assistant.realtime")

TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=3.0)

INSTRUCTIONS = """You are a telecom customer assistant on a live voice call.

You have tools to look up the caller's real account: get_profile, get_device_details,
get_balance, get_purchase_history, get_offers. Always call the matching tool instead of
guessing when asked about their account — never invent numbers or details. If a request
is ambiguous (e.g. "check my plan" could mean their current plan or available offers),
ask a short clarifying question before calling a tool. Keep responses brief and
conversational, suited for speech, not a written report.

Always reply in the same language the caller just spoke, whatever it is (Telugu,
Hindi, English, or any other language) — never default to Hindi or English just
because it's more common; match the caller's actual language on every turn, even
if it changes partway through the call."""

# Zero-argument tools: the model can only request an intent by name, never
# supply parameters (e.g. a phone number) — mobileNumber stays server-side,
# same rule as the chat path.
REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "get_profile",
        "description": "Get the customer's account profile and current plan details.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_device_details",
        "description": "Get the customer's registered device and SIM details.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_balance",
        "description": "Get the customer's current balance, and data/voice/SMS remaining.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_purchase_history",
        "description": "Get the customer's recent purchases and recharges.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_offers",
        "description": "Get offers and plans available for the customer to buy.",
        "parameters": {"type": "object", "properties": {}},
    },
]

FUNCTION_NAME_TO_INTENT = {
    "get_profile": "PROFILE",
    "get_device_details": "DEVICE_DETAILS",
    "get_balance": "BALANCE",
    "get_purchase_history": "PURCHASE_HISTORY",
    "get_offers": "OFFERS",
}

assert set(FUNCTION_NAME_TO_INTENT.values()) == set(TOOL_REGISTRY.keys())


class RealtimeSessionResult(BaseModel):
    success: bool
    client_secret: str | None = None
    realtime_url: str | None = None
    error: str | None = None


async def create_realtime_session() -> RealtimeSessionResult:
    """Mints a short-lived ephemeral token via Azure OpenAI's GA realtime
    endpoint. The long-lived AZURE_OPENAI_API_KEY never leaves this backend;
    only the ephemeral token (and the public realtime_url) go to the browser.
    """
    settings = get_settings()
    url = f"{settings.azure_openai_endpoint}/realtime/client_secrets"

    audio_input: dict = {
        # Explicit even though server_vad is the default — makes the
        # automatic end-of-speech -> response behavior unambiguous.
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
            "create_response": True,
        },
    }
    if settings.azure_openai_transcribe_deployment:
        # Azure requires a deployment name here, not a bare model name like
        # "whisper-1" — only send this if the user configured one, since a
        # wrong deployment name can make the whole session config reject.
        audio_input["transcription"] = {"model": settings.azure_openai_transcribe_deployment}

    payload = {
        "session": {
            "type": "realtime",
            "model": settings.azure_openai_realtime_deployment,
            "instructions": INSTRUCTIONS,
            "audio": {"input": audio_input, "output": {"voice": "alloy"}},
            "tools": REALTIME_TOOLS,
            "tool_choice": "auto",
        }
    }
    headers = {"api-key": settings.azure_openai_api_key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        client_secret = data.get("value")
        if not client_secret:
            logger.warning("realtime_session_missing_client_secret")
            return RealtimeSessionResult(success=False, error="realtime_session_invalid_response")

        return RealtimeSessionResult(
            success=True,
            client_secret=client_secret,
            realtime_url=f"{settings.azure_openai_endpoint}/realtime/calls",
        )

    except httpx.TimeoutException:
        logger.warning("realtime_session_timeout")
        return RealtimeSessionResult(success=False, error="realtime_session_timeout")

    except httpx.HTTPStatusError as exc:
        logger.warning("realtime_session_http_error status=%s", exc.response.status_code)
        return RealtimeSessionResult(success=False, error="realtime_session_error")

    except httpx.RequestError:
        logger.warning("realtime_session_request_error")
        return RealtimeSessionResult(success=False, error="realtime_session_unreachable")

    except ValueError:
        logger.warning("realtime_session_invalid_response")
        return RealtimeSessionResult(success=False, error="realtime_session_invalid_response")
