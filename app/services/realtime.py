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

LANGUAGE — decide the reply language from the caller's MOST RECENT message only.
Never from earlier turns, and never from the language you yourself used last
time. If the caller spoke Hindi for five turns and then asks something in
Telugu, that reply must be in Telugu; if the next message is in English, switch
to English. Do not carry the previous language forward, and do not default to
Hindi or English because they're more common. This applies to the reply you
give after a tool call too — the language is set by the caller's question, not
by the tool data. If these instructions end with a line starting "CURRENT
CALLER LANGUAGE:", treat that line as authoritative for the next reply.

When speaking Hindi, Telugu, Tamil, or any other Indian language, use simple,
everyday spoken words — the way people actually talk, not formal or literary
"book" vocabulary/grammar. Prefer common words over Sanskrit-heavy or
formal-register ones (e.g. plain conversational Hindi over shuddh/literary
Hindi). Short, easy sentences — this is a phone call, not a written
announcement."""

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
    # A full "session.update" event for the browser to send once connected,
    # present only when transcription is configured. Deliberately the FULL
    # session (instructions, tools, voice, turn_detection — not just the
    # transcription field) — Azure's session.update appears to replace nested
    # objects wholesale rather than deep-merge them, so omitting any field
    # here risks silently resetting it. Confirmed live: sending only the
    # transcription field reset the voice to something other than the one
    # fixed at mint time. Built from the exact same _session_config() as the
    # mint-time payload so there is a single source of truth — nothing can
    # drift between the two the way the voice did.
    post_connect_update: dict | None = None


def _session_config(transcribe_model: str | None) -> dict:
    settings = get_settings()
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
    if transcribe_model:
        audio_input["transcription"] = {"model": transcribe_model}

    return {
        "type": "realtime",
        "model": settings.azure_openai_realtime_deployment,
        "instructions": INSTRUCTIONS,
        "audio": {"input": audio_input, "output": {"voice": "alloy"}},
        "tools": REALTIME_TOOLS,
        "tool_choice": "auto",
    }


async def create_realtime_session() -> RealtimeSessionResult:
    """Mints a short-lived ephemeral token via Azure OpenAI's GA realtime
    endpoint. The long-lived AZURE_OPENAI_API_KEY never leaves this backend;
    only the ephemeral token (and the public realtime_url) go to the browser.
    """
    settings = get_settings()
    url = f"{settings.azure_openai_endpoint}/realtime/client_secrets"

    # Transcription is deliberately excluded from the mint-time payload even
    # though the deployment name is valid — Azure's client_secrets endpoint
    # fails to resolve a transcription deployment there (DeploymentNotFound,
    # confirmed live). It's enabled after connecting instead, via
    # post_connect_update below.
    payload = {"session": _session_config(transcribe_model=None)}
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

        post_connect_update = None
        if settings.azure_openai_transcribe_deployment:
            post_connect_update = {
                "type": "session.update",
                "session": _session_config(transcribe_model=settings.azure_openai_transcribe_deployment),
            }

        return RealtimeSessionResult(
            success=True,
            client_secret=client_secret,
            realtime_url=f"{settings.azure_openai_endpoint}/realtime/calls",
            post_connect_update=post_connect_update,
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
