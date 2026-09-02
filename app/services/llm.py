import asyncio
import json
import logging

from openai import APIError, APITimeoutError, AsyncAzureOpenAI

from app.config import get_settings

logger = logging.getLogger("telecom_assistant.llm")

TIMEOUT_SECONDS = 4.0

FALLBACK_RESULT = {
    "intent": "UNKNOWN",
    "confidence": 0.0,
    "possible_intents": [],
    "clarification_question": "",
}

SYSTEM_PROMPT = """You are the intent classifier for a telecom customer assistant.

Classify the user's message into exactly one of these intents:
- PROFILE: account/profile/plan details, customer status
- DEVICE_DETAILS: phone/device/SIM information
- BALANCE: account balance, data/voice/SMS remaining
- PURCHASE_HISTORY: past purchases/recharges/transactions
- OFFERS: available offers/plans/deals to buy
- UNKNOWN: anything else, or the message is too vague to classify

Be tolerant of typos and casual phrasing (e.g. "balence" means BALANCE).

If the message could plausibly mean more than one intent (e.g. "check my plan"
could mean PROFILE or OFFERS), set confidence below 0.5, list the plausible
intents in possible_intents, and write a short natural-language question in
clarification_question that would resolve the ambiguity.
{candidate_note}
Respond with ONLY a JSON object of this exact shape, no other text:
{{
  "intent": "<one of PROFILE, DEVICE_DETAILS, BALANCE, PURCHASE_HISTORY, OFFERS, UNKNOWN>",
  "confidence": <float between 0.0 and 1.0>,
  "possible_intents": [<intent strings, only when genuinely ambiguous, else []>],
  "clarification_question": "<short question, only when ambiguous, else empty string>"
}}"""

CANDIDATE_NOTE_TEMPLATE = (
    "\nThe user is answering your own earlier clarification question. Choose "
    "between these candidate intents unless the reply clearly means something "
    "else: {candidates}.\n"
)


def _client() -> AsyncAzureOpenAI:
    settings = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


async def classify_intent(message: str, candidate_intents: list[str] | None = None) -> dict:
    """Classifies a message via Azure OpenAI. Never raises: any failure
    (timeout, API error, malformed response) yields FALLBACK_RESULT so the
    caller treats it as low-confidence and asks for clarification instead of
    calling a telecom API on a guess.
    """
    settings = get_settings()
    candidate_note = (
        CANDIDATE_NOTE_TEMPLATE.format(candidates=", ".join(candidate_intents))
        if candidate_intents
        else ""
    )
    system_prompt = SYSTEM_PROMPT.format(candidate_note=candidate_note)

    try:
        async with _client() as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.azure_openai_deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                ),
                timeout=TIMEOUT_SECONDS,
            )
        return json.loads(response.choices[0].message.content)

    except (TimeoutError, APITimeoutError):
        logger.warning("llm_timeout")
    except APIError:
        logger.warning("llm_api_error")
    except (ValueError, KeyError, IndexError):
        logger.warning("llm_invalid_response")

    return dict(FALLBACK_RESULT)
