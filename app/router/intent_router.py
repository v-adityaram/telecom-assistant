from app.config import get_settings
from app.router.confidence import build_router_result
from app.router.schemas import RouterResult
from app.services.llm import classify_intent


async def route_intent(
    message: str, candidate_intents: list[str] | None = None, history: list[dict] | None = None
) -> RouterResult:
    settings = get_settings()
    raw = await classify_intent(message, candidate_intents=candidate_intents, history=history)
    threshold = (
        settings.intent_followup_confidence_threshold
        if candidate_intents
        else settings.intent_confidence_threshold
    )
    return build_router_result(raw, threshold)
