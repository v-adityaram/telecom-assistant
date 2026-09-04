import asyncio
import re
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.router.confidence import BUY_OFFER_INTENT, COMPLEX_INTENT
from app.router.intent_router import route_intent
from app.services import conversation_store
from app.services.answer_synthesis import synthesize_specific_answer
from app.services.complex_flow import run_complex_flow
from app.services.customer_context import get_customer_context
from app.services.purchase_flow import run_buy_offer_flow
from app.services.response import render_answer_message
from app.services.session_store import PendingClarification, clear_pending, get_pending, set_pending
from app.tools.registry import execute_tool

router = APIRouter()

# Matches a run of digits (with optional embedded spaces/dashes) that's the
# right shape for an Indian mobile number: 10 digits bare, or 12 with a "91"
# country code — deliberately excludes other digit-string lengths (IMEIs are
# 15, OTPs are 4-6) so those don't false-positive here.
_DIGIT_RUN = re.compile(r"\d[\d\s-]*\d|\d")


def _mentions_different_account(message: str, mobile_number: str) -> bool:
    own = re.sub(r"\D", "", mobile_number)[-10:]
    for token in _DIGIT_RUN.findall(message):
        digits = re.sub(r"\D", "", token)
        if len(digits) in (10, 12) and digits[-10:] != own:
            return True
    return False


def _load_history(session_id: str, mobile_number: str) -> list[dict]:
    conversation = conversation_store.get_conversation(session_id, mobile_number)
    return (conversation or {}).get("messages") or []


def _persist_turn(
    session_id: str, mobile_number: str, history: list[dict], user_message: str, assistant_message: str
) -> None:
    updated = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_message},
    ]
    conversation_store.upsert_conversation(session_id, mobile_number, updated)


class ChatRequest(BaseModel):
    message: str
    # Sourced directly from the request, never from the model/message text.
    # Real auth (Phase 11) will replace this with a session-derived value —
    # this is the seam app/services/customer_context.py already documents.
    mobile_number: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    type: str
    session_id: str
    intent: str | None = None
    message: str
    data: dict | None = None
    possible_intents: list[str] | None = None


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid.uuid4())
    # session_id doubles as the Cosmos conversation_id — same identifier the
    # frontend already keeps stable for a chat, one fewer concept to invent.
    history = await asyncio.to_thread(_load_history, session_id, request.mobile_number)

    async def _persist(assistant_message: str) -> None:
        await asyncio.to_thread(
            _persist_turn, session_id, request.mobile_number, history, request.message, assistant_message
        )

    if _mentions_different_account(request.message, request.mobile_number):
        message = (
            "I can only look up the account you're signed in with — not other "
            "phone numbers. Ask me about your own profile, device, balance, "
            "purchase history, or offers."
        )
        await _persist(message)
        return ChatResponse(type="answer", session_id=session_id, message=message)

    pending = get_pending(session_id)
    candidate_intents = pending.possible_intents if pending else None

    result = await route_intent(request.message, candidate_intents=candidate_intents, history=history)

    if result.needs_clarification:
        set_pending(
            session_id,
            PendingClarification(
                original_message=request.message,
                possible_intents=result.possible_intents,
            ),
        )
        await _persist(result.clarification_message)
        return ChatResponse(
            type="clarification",
            session_id=session_id,
            message=result.clarification_message,
            possible_intents=result.possible_intents or None,
        )

    clear_pending(session_id)

    if result.intent == COMPLEX_INTENT:
        answer, fetched = await run_complex_flow(request.message, request.mobile_number, history)
        await _persist(answer)
        return ChatResponse(
            type="answer",
            session_id=session_id,
            intent=COMPLEX_INTENT,
            message=answer,
            data=fetched or None,
        )

    if result.intent == BUY_OFFER_INTENT:
        answer = await run_buy_offer_flow(request.message, request.mobile_number, history)
        await _persist(answer)
        return ChatResponse(
            type="answer",
            session_id=session_id,
            intent=BUY_OFFER_INTENT,
            message=answer,
        )

    customer = get_customer_context(request.mobile_number)
    tool_result = await execute_tool(result.intent, customer)

    if not tool_result.success:
        message = "Sorry, I couldn't fetch that right now. Please try again shortly."
        await _persist(message)
        return ChatResponse(
            type="error",
            session_id=session_id,
            intent=result.intent,
            message=message,
        )

    if result.scope == "specific":
        single_tool_data = (tool_result.data or {}).get("data") or {}
        message = await synthesize_specific_answer(request.message, {result.intent: single_tool_data})
    else:
        message = render_answer_message(result.intent, tool_result.data)

    await _persist(message)
    return ChatResponse(
        type="answer",
        session_id=session_id,
        intent=result.intent,
        message=message,
        data=tool_result.data,
    )
