"""LangGraph fallback for requests the fast single-intent path can't answer
well: ones that genuinely need data from more than one of the 5 areas (e.g.
"am I eligible for 5G" spans PROFILE and DEVICE_DETAILS), or that ask for
reasoning/advice grounded in account data rather than a raw lookup.

Graph: START -> plan -> fetch -> answer -> END. Independent tool fetches run
concurrently inside the fetch node (asyncio.gather) rather than as separate
LangGraph branches, per the plan's "independent operations execute
concurrently" rule — kept as one node since a dict of results is all "answer"
needs, and StateGraph's fan-out/fan-in machinery isn't needed for that.

Every failure mode degrades to an honest message rather than raising or
fabricating account data: an LLM call that fails yields an empty plan or a
safe fallback answer, and any tool name outside the allow-list is dropped
before it ever reaches execute_tool — the same defense-in-depth `chat.py`
and the registry already apply, since a LangGraph node is still just
untrusted model output until it's checked.
"""

import asyncio
import json
import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from openai import APIError, APITimeoutError, AsyncOpenAI

from app.config import get_settings
from app.services.customer_context import get_customer_context
from app.tools.registry import TOOL_REGISTRY, execute_tool

logger = logging.getLogger("telecom_assistant.complex_flow")

TIMEOUT_SECONDS = 6.0
ALLOWED_TOOLS = set(TOOL_REGISTRY.keys())

PLAN_PROMPT = """You are planning which account-data lookups are needed to
answer a telecom customer's message. Available lookups: PROFILE,
DEVICE_DETAILS, BALANCE, PURCHASE_HISTORY, OFFERS.

Pick every lookup whose data is relevant — it's fine and expected to pick more
than one, or all five, if the question genuinely spans them. If the message
is unrelated to the caller's telecom account or service entirely — general
knowledge, trivia, jokes, coding help, current events, or anything else
outside their account — return an empty list; the next step declines
politely rather than answering it.

Calibration — always include every listed tool for these topics, not just one:
- add-ons / add ons -> ["BALANCE", "OFFERS"] (BALANCE has the add-ons already
  on the account under addOnBalances; OFFERS has add-on offers to buy —
  answering "what are my add-ons" needs both, not just one)
- 5G eligibility -> ["PROFILE", "DEVICE_DETAILS"] (PROFILE has the account's
  5G eligibility flag; DEVICE_DETAILS has the device/network's 5G support)
- roaming -> ["PROFILE", "OFFERS"] (PROFILE has whether roaming is enabled;
  OFFERS has roaming packs available to buy)

Respond with ONLY a JSON object of this exact shape, no other text:
{"tools": ["PROFILE", "OFFERS"]}"""

ANSWER_PROMPT = """You are a telecom customer assistant answering the customer's
latest message using real account data that was just looked up for this turn,
plus the recent conversation so far (given to you as prior turns, oldest first).

SCOPE — you only help with the caller's telecom account and service: their
profile/plan, device/SIM, balance, purchase history, offers, AND this
conversation itself. Questions about the conversation — "what did I ask",
"what have we talked about", "go back to my balance question", "summarize
this chat" — are in scope: answer those from the conversation history below,
no fresh account-data lookup is needed for them. If the message is unrelated
to both the account and the conversation so far (general knowledge, trivia,
jokes, coding help, current events, or anything else) — including when the
account data below is empty because it needed no lookup — do NOT answer it,
even if you know the answer. Instead decline warmly with something like:
"I can only help with your telecom account and services — your plan, balance,
device, purchase history, or offers. I'm not able to help with that, but I'm
happy to check any of those for you!" You may still use general knowledge to
help INTERPRET an account-related question (e.g. knowing a city is in India
to answer a roaming question) — just never to answer something that has
nothing to do with the account or this conversation.

Otherwise, answer directly and concisely, grounded only in the data and
conversation below — never invent numbers, plans, or account details that
aren't in them. If the data doesn't contain what's needed, say so honestly
instead of guessing.

Account data just looked up for this turn (JSON; a lookup marked "error"
failed and has no data):
{data_json}

Reply in plain conversational text — no JSON, no markdown headers, a few
sentences at most."""

FALLBACK_ANSWER = (
    "Sorry, I couldn't work that out right now. Could you ask about a specific "
    "area — your profile, device details, balance, purchase history, or offers?"
)


class ComplexState(TypedDict):
    message: str
    mobile_number: str
    plan: list[str]
    fetched: dict
    answer: str
    history: list[dict]


def _client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(base_url=settings.azure_openai_endpoint, api_key=settings.azure_openai_api_key)


async def _plan_node(state: ComplexState) -> dict:
    settings = get_settings()
    try:
        async with _client() as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.azure_openai_deployment,
                    messages=[
                        {"role": "system", "content": PLAN_PROMPT},
                        {"role": "user", "content": state["message"]},
                    ],
                    reasoning_effort="minimal",
                    max_completion_tokens=100,
                    response_format={"type": "json_object"},
                ),
                timeout=TIMEOUT_SECONDS,
            )
        raw = json.loads(response.choices[0].message.content)
        tools = [t for t in raw.get("tools") or [] if t in ALLOWED_TOOLS]
        return {"plan": tools}
    except (TimeoutError, APITimeoutError, APIError, ValueError, KeyError):
        logger.warning("complex_flow_plan_failed")
        return {"plan": []}


async def _fetch_node(state: ComplexState) -> dict:
    tools = state["plan"]
    if not tools:
        return {"fetched": {}}

    customer = get_customer_context(state["mobile_number"])
    results = await asyncio.gather(*(execute_tool(intent, customer) for intent in tools))

    fetched = {}
    for intent, result in zip(tools, results, strict=True):
        if result.success:
            fetched[intent] = (result.data or {}).get("data") or {}
        else:
            fetched[intent] = {"error": result.error or "lookup_failed"}
    return {"fetched": fetched}


async def _answer_node(state: ComplexState) -> dict:
    settings = get_settings()
    prompt = ANSWER_PROMPT.format(data_json=json.dumps(state["fetched"]))
    # Real prior turns, not folded into the system prompt — lets the model
    # answer meta-questions ("what did I ask") from actual conversation
    # history instead of only ever seeing the current message in isolation.
    messages = [{"role": "system", "content": prompt}]
    messages.extend(state.get("history") or [])
    messages.append({"role": "user", "content": state["message"]})
    try:
        async with _client() as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.azure_openai_deployment,
                    messages=messages,
                    reasoning_effort="minimal",
                    max_completion_tokens=300,
                ),
                timeout=TIMEOUT_SECONDS,
            )
        answer = response.choices[0].message.content or FALLBACK_ANSWER
        return {"answer": answer}
    except (TimeoutError, APITimeoutError, APIError, ValueError, KeyError):
        logger.warning("complex_flow_answer_failed")
        return {"answer": FALLBACK_ANSWER}


_graph = StateGraph(ComplexState)
_graph.add_node("plan", _plan_node)
_graph.add_node("fetch", _fetch_node)
_graph.add_node("answer", _answer_node)
_graph.add_edge(START, "plan")
_graph.add_edge("plan", "fetch")
_graph.add_edge("fetch", "answer")
_graph.add_edge("answer", END)
_compiled = _graph.compile()


async def run_complex_flow(
    message: str, mobile_number: str, history: list[dict] | None = None
) -> tuple[str, dict]:
    """Returns (answer_message, fetched_data) — fetched_data is included in the
    chat response's `data` field the same way a single-tool answer includes it.
    `history` is this conversation's prior turns (oldest first, already
    role/content dicts) — capped here so a long-running chat can't blow up
    token cost/latency on every COMPLEX turn.
    """
    result = await _compiled.ainvoke(
        {
            "message": message,
            "mobile_number": mobile_number,
            "plan": [],
            "fetched": {},
            "answer": "",
            "history": (history or [])[-20:],
        }
    )
    return result["answer"], result["fetched"]
