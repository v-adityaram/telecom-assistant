import asyncio
import json
import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

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
- COMPLEX: needs real data from more than one of the areas above to answer
  well, or asks for reasoning/advice using account data, or bundles multiple
  explicit requests in one message — see the COMPLEX section below
- UNKNOWN: anything else, or the message is too vague to classify

Be tolerant of typos and casual phrasing (e.g. "balence" means BALANCE).

Calibration examples (confidence >= 0.9 when the meaning is this clear):
- "what's my balance?" / "what is my balence?" / "how much money do I have?" -> BALANCE
- "show me my phone" / "what's my SIM status" / "esim flag?" / "is my sim
  esim" / "sim type" -> DEVICE_DETAILS (all SIM details, including whether
  it's an eSIM, live only in DEVICE_DETAILS — never treat a bare SIM/eSIM
  question as too vague to classify)
- "what did I buy?" / "what was my last recharge" -> PURCHASE_HISTORY
- "what offers do I have?" / "any deals for me" -> OFFERS
- "show my details" / "am I prepaid or postpaid" -> PROFILE
- "check my plan" / "what's my plan" / "my plan" -> ALWAYS ambiguous, confidence
  below 0.5, possible_intents ["PROFILE","OFFERS"] — "plan" alone never means
  the current plan specifically; it is equally likely to mean plans available
  to buy. Do not resolve this to PROFILE directly no matter how the sentence
  is phrased, unless the message also says something like "current" or
  "existing" ("what's my current plan" -> PROFILE) or "new"/"buy"/"switch"
  ("what plans can I buy" -> OFFERS).

There is no separate SMS/text-messages intent — SMS remaining is one field
inside BALANCE, same as data and voice minutes. Any message about SMS,
texts, or messages remaining maps to BALANCE, even short ones with no other
context: "sms", "sms bal", "texts left", "how many messages do I have" ->
BALANCE at confidence >= 0.9. Do not treat a bare "sms" as too vague to
classify — it is not ambiguous between two known intents, it always means
BALANCE.

COMPLEX — use this when a quick clarifying question wouldn't actually help,
because the answer genuinely needs more than a single lookup. Examples:
- "what are my add-ons" -> COMPLEX (could mean add-ons you already have —
  BALANCE — or add-on offers to buy — OFFERS; answering well needs both, not
  a binary pick)
- "am I eligible for 5G" -> COMPLEX (depends on both your plan's PROFILE flags
  and your DEVICE_DETAILS/SIM capability)
- "what roaming charges or offers do I have" -> COMPLEX (needs current
  roaming status AND available roaming offers)
- "should I get a roaming pack for my trip to Vizag" -> COMPLEX (asks for
  advice grounded in account data, not a raw lookup)
- "check my balance and tell me what offers I have" -> COMPLEX (two explicit
  requests in one message)
Set confidence 0.9 for a clear COMPLEX case; possible_intents and
clarification_question are not used when intent is COMPLEX (leave them empty).
Do NOT use COMPLEX for "check my plan" / "what's my plan" / bare "plan" —
that stays the normal PROFILE-vs-OFFERS clarification below; a quick pick
resolves it, no deeper lookup needed.

If the message could plausibly mean exactly one of two single-lookup intents
(e.g. "check my plan" could mean PROFILE or OFFERS, and a quick pick from the
user would resolve it), set confidence below 0.5, list the plausible intents
in possible_intents, and write a short natural-language question in
clarification_question that would resolve the ambiguity.

If the message is a greeting, small talk, a question about you/the assistant
itself, or otherwise clearly UNKNOWN (not ambiguous between two of the known
intents — genuinely unrelated to the account), still set confidence below 0.5
and still write a clarification_question, but make it a brief, friendly
response that greets the user back if relevant and tells them what you can
help with (profile, device details, balance, purchase history, or offers) —
never leave clarification_question empty just because nothing matched.
{candidate_note}
Respond with ONLY a JSON object of this exact shape, no other text:
{{
  "intent": "<one of PROFILE, DEVICE_DETAILS, BALANCE, PURCHASE_HISTORY, OFFERS, COMPLEX, UNKNOWN>",
  "confidence": <float between 0.0 and 1.0>,
  "possible_intents": [<intent strings, only when genuinely ambiguous between known intents, else []>],
  "clarification_question": "<a short question or friendly redirect whenever confidence is below 0.5>"
}}"""

CANDIDATE_NOTE_TEMPLATE = (
    "\nThe user is answering your own earlier clarification question, choosing "
    "between these candidate intents: {candidates}. Short replies are normal here "
    "— \"the available ones\" / \"the ones I can buy\" mean OFFERS, \"my current "
    "one\" / \"the one I'm on\" mean PROFILE. If the reply picks one candidate, "
    "return that intent with confidence 0.9 or higher and an empty "
    "possible_intents. Only stay below 0.5 if the reply genuinely fits none of "
    "them or clearly asks for something else entirely.\n"
)


def _client() -> AsyncOpenAI:
    # Azure OpenAI's unified v1 API surface: base_url already ends in
    # /openai/v1, model= is the Azure deployment name, no api-version needed.
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
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
                    # gpt-5 models reject temperature != default; minimal
                    # reasoning effort keeps this fast for a plain classification.
                    reasoning_effort="minimal",
                    max_completion_tokens=200,
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
