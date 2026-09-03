import asyncio
import json
import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger("telecom_assistant.llm")

TIMEOUT_SECONDS = 6.0  # observed real calls taking up to ~4.5s; 4.0 was too tight

FALLBACK_RESULT = {
    "intent": "UNKNOWN",
    "confidence": 0.0,
    "possible_intents": [],
    "clarification_question": "",
    "scope": "full",
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
- "is my phone 5g" / "does my phone support 5g" / "is my device 5g
  compatible" -> DEVICE_DETAILS at confidence >= 0.9 (asking about the
  physical device's hardware capability — networkCapability lives only in
  DEVICE_DETAILS). This is NOT the same as "am I eligible for 5G" / "is my
  plan 5G" (that's account-level eligibility, spans PROFILE too — see
  COMPLEX below). "phone"/"device" -> DEVICE_DETAILS only; "eligible"/"plan"
  -> COMPLEX.
- "what did I buy?" / "what was my last recharge" -> PURCHASE_HISTORY
- "what offers do I have?" / "any deals for me" -> OFFERS
- "show my details" / "am I prepaid or postpaid" / "profile" (bare, alone)
  -> PROFILE at confidence >= 0.9. Unlike "plan" below, the word "profile" by
  itself is NOT ambiguous with OFFERS — it never means "offers" or "plans to
  buy", it only ever means the account/profile itself. Do not apply the
  "plan" ambiguity rule to the word "profile".
- "check my plan" / "what's my plan" / "my plan" -> ALWAYS ambiguous, confidence
  below 0.5, possible_intents ["PROFILE","OFFERS"] — "plan" alone never means
  the current plan specifically; it is equally likely to mean plans available
  to buy. Do not resolve this to PROFILE directly no matter how the sentence
  is phrased, unless the message also says something like "current" or
  "existing" ("what's my current plan" -> PROFILE) or "new"/"buy"/"switch"
  ("what plans can I buy" -> OFFERS). This rule is specifically about the word
  "plan" — it does not extend to "profile" (see above) or to "5G" (see below).
- "where is my sim based" / "where am I based" / "location?" / "which circle
  am I on" / "what telecom circle" -> PROFILE at confidence >= 0.9, scope
  "specific" (this is the account's telecomCircle field — real data, not a
  request for GPS/live location). Never treat a location/circle question as
  too vague to classify.

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

GUARDRAIL — this includes any question with nothing to do with the caller's
telecom account (general knowledge, trivia, jokes, coding help, current
events, etc.). Never answer it yourself even if you know the answer — always
redirect, e.g.: "I can only help with your telecom account and services —
your plan, balance, device, purchase history, or offers. I'm not able to
help with that, but I'm happy to check any of those for you!" Vary the
wording naturally rather than repeating this verbatim every time, but keep
the same meaning: this assistant only ever answers from real account data.

scope — for a resolved single-lookup intent (not COMPLEX, not a clarification),
decide whether the user asked broadly or about one specific fact:
- "full": the user asked broadly for a whole category — "what's my balance",
  "show my details", "show my device", "what offers do I have", "what did I
  buy" — they want the full picture, not just one field.
- "specific": the user named one particular fact within that category and
  only that fact should be answered — "sms" / "sms bal" (just SMS, not the
  whole balance), "is my phone 5g" / "does it support 5g" (just yes/no),
  "esim flag" / "is my sim esim" (just that), "how much data do I have left"
  (just data), "is auto-renew on" (just that), "what's my IMEI" (just that),
  "what was my last recharge" / "what was my most recent purchase" (the one
  specific transaction they named, not the whole history).
Default to "full" whenever unsure — only use "specific" when the message
clearly names one narrow fact, not a whole category. For purchase history
specifically: "recently" without "last"/"most recent" still means the list —
"what did I buy recently" / "what did I buy" -> full (show the recent
purchases, not just one — dropping down to a single item here would wrongly
imply that's their only purchase); only "last"/"most recent" (singular,
explicitly asking about the one latest transaction) -> specific.
{candidate_note}
Respond with ONLY a JSON object of this exact shape, no other text:
{{
  "intent": "<one of PROFILE, DEVICE_DETAILS, BALANCE, PURCHASE_HISTORY, OFFERS, COMPLEX, UNKNOWN>",
  "confidence": <float between 0.0 and 1.0>,
  "possible_intents": [<intent strings, only when genuinely ambiguous between known intents, else []>],
  "clarification_question": "<a short question or friendly redirect whenever confidence is below 0.5>",
  "scope": "<'full' or 'specific', only meaningful when intent is one of the 5 lookups>"
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
