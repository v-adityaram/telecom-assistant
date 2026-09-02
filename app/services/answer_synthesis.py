"""Answers a narrow, single-fact question ("sms", "is my phone 5g") grounded
in data already fetched for one intent, instead of reciting the full
`app/services/response.py` template.

Kept as a separate, opt-in path rather than the default: most questions are
broad ("what's my balance") and the deterministic template already answers
those well and instantly. This only runs when the router itself decides the
question named one specific fact (`RouterResult.scope == "specific"`), so the
common case pays no extra latency or cost.

Same trust model as `complex_flow.py`'s answer node and voice: the model
never sees anything but the real data already fetched through the Phase 3
tool registry, but is allowed to phrase/extract from it — it cannot call
tools or invent account facts, only summarize what's already there.
"""

import asyncio
import json
import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger("telecom_assistant.answer_synthesis")

TIMEOUT_SECONDS = 5.0

SPECIFIC_ANSWER_PROMPT = """You are a telecom customer assistant. The customer
asked a narrow, specific question, and real account data was just looked up
to answer it.

Answer ONLY the specific thing they asked — do not recite the whole data
dump, do not add unrelated fields. One or two sentences, direct and
conversational.

Ground your answer only in the data below — never invent numbers or details
that aren't in it. If the data doesn't contain what's needed, say so
honestly instead of guessing.

Account data (JSON):
{data_json}

User's question: {message}

Reply in plain conversational text — no JSON, no markdown."""

FALLBACK_ANSWER = "Sorry, I couldn't work that out right now — please try again in a moment."


def _client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(base_url=settings.azure_openai_endpoint, api_key=settings.azure_openai_api_key)


async def synthesize_specific_answer(message: str, data: dict) -> str:
    """Never raises: any failure (timeout, API error, malformed response)
    degrades to FALLBACK_ANSWER rather than guessing or crashing.
    """
    settings = get_settings()
    prompt = SPECIFIC_ANSWER_PROMPT.format(data_json=json.dumps(data), message=message)

    try:
        async with _client() as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.azure_openai_deployment,
                    messages=[{"role": "system", "content": prompt}],
                    reasoning_effort="minimal",
                    max_completion_tokens=150,
                ),
                timeout=TIMEOUT_SECONDS,
            )
        return response.choices[0].message.content or FALLBACK_ANSWER

    except (TimeoutError, APITimeoutError, APIError, ValueError, KeyError):
        logger.warning("answer_synthesis_failed")
        return FALLBACK_ANSWER
