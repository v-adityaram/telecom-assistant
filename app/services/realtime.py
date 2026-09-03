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

LANGUAGE — the app tells you the caller's language each turn with a line at the
end of these instructions starting "CURRENT CALLER LANGUAGE:". Follow it
exactly and reply in that language. When that line says the caller just
switched languages: answer this message in the new language, then add one
short question, in the new language, asking whether to continue in it — and
from then on use the new language until the line changes again. Never announce
a language policy of your own and never say you'll stay in an earlier language.
This applies to the reply you give after a tool call too — the caller's
question sets the language, not the tool data. If no such line is present,
reply in the language of the caller's most recent message; never carry an
earlier turn's language forward, and never default to Hindi or English because
they're common.

DATA HONESTY — the tools return exactly what the account holds, nothing more.
The profile has NO customer name: only a customer ID, the phone number, plan,
status, segment, telecom circle, activation date, preferences and service
flags. If the caller asks for something that isn't in the data — their name
is the common case — say plainly, in one sentence, that it isn't available in
the account details you can see, then offer what you do have (e.g. the
customer ID or the number ending). Never invent a reason: do not say it's
withheld for privacy or security, do not claim a policy, do not ask the caller
to tell you their name so you can "confirm" it. Absent data is absent data.

SCOPE — you only help with the caller's telecom account and service: their
profile/plan, device/SIM, balance, purchase history, and offers (small talk
like a greeting or "how are you" is fine to answer briefly and warmly). For
anything else — general knowledge, trivia, jokes, coding help, current
events, or any other topic with nothing to do with their account — do not
answer it, even if you know the answer. Decline warmly and briefly, in the
caller's current language, with something like: "I can only help with your
telecom account — your plan, balance, device, purchase history, or offers.
I can't help with that, but happy to check any of those for you!" Say the
equivalent in whatever language you're currently speaking, in the same
simple everyday register as the rest of the call — don't just switch to
English for this line.

NUMBERS — say every number in English regardless of the sentence language:
amounts ("one hundred two rupees and fifty paise"), data ("three four eight
five MB" or "about three point five GB"), dates, minutes, SMS counts, and IDs
like the IMEI (read its digits in English). Only the numbers — the words
around them stay in the caller's language.

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
            # With transcription on, the browser triggers each response itself
            # (response.create) *after* it has the caller's transcript, so it
            # can state the caller's language deterministically first — the
            # model kept answering in the previous turn's language on switches
            # when left to infer. Without transcription there's nothing to wait
            # for, so the server auto-responds as before.
            "create_response": transcribe_model is None,
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
