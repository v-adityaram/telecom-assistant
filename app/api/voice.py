from fastapi import APIRouter
from pydantic import BaseModel

from app.services.customer_context import get_customer_context
from app.services.realtime import FUNCTION_NAME_TO_INTENT, create_realtime_session
from app.services.turn_credentials import generate_turn_credentials
from app.tools.registry import execute_tool

router = APIRouter()


class VoiceSessionResponse(BaseModel):
    success: bool
    client_secret: str | None = None
    realtime_url: str | None = None
    error: str | None = None
    post_connect_update: dict | None = None
    # Present only when TURN_SHARED_SECRET/TURN_DOMAIN are configured (see
    # app/services/turn_credentials.py) — time-limited, never a standing
    # secret shipped to the browser. None means "no TURN relay configured",
    # not a failure — the frontend falls back to STUN-only in that case.
    turn: dict | None = None


@router.post("/api/voice/session", response_model=VoiceSessionResponse)
async def voice_session() -> VoiceSessionResponse:
    result = await create_realtime_session()
    return VoiceSessionResponse(**result.model_dump(), turn=generate_turn_credentials())


class VoiceToolRequest(BaseModel):
    function_name: str
    # Sourced directly from the caller, same seam as ChatRequest.mobile_number
    # — never supplied by the realtime model itself (its tools take no args).
    mobile_number: str


class VoiceToolResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None


@router.post("/api/voice/tool", response_model=VoiceToolResponse)
async def voice_tool(request: VoiceToolRequest) -> VoiceToolResponse:
    intent = FUNCTION_NAME_TO_INTENT.get(request.function_name)
    if intent is None:
        return VoiceToolResponse(success=False, error="unknown_function")

    customer = get_customer_context(request.mobile_number)
    tool_result = await execute_tool(intent, customer)

    if not tool_result.success:
        return VoiceToolResponse(success=False, error=tool_result.error or "tool_error")

    payload = (tool_result.data or {}).get("data") or {}
    return VoiceToolResponse(success=True, data=payload)
