from app.router.schemas import RouterResult
from app.tools.registry import TOOL_REGISTRY

ALLOWED_INTENTS = set(TOOL_REGISTRY.keys())

DEFAULT_CLARIFICATION_MESSAGE = (
    "I'm not sure what you're asking. Could you tell me if you want your "
    "profile, device details, balance, purchase history, or offers?"
)


def build_router_result(raw: dict, threshold: float) -> RouterResult:
    """Turns the LLM's raw JSON into a RouterResult, enforcing the confidence
    threshold and the intent allow-list. An intent outside ALLOWED_INTENTS
    (hallucinated or malformed) is never treated as high-confidence — it
    always falls through to clarification, so no telecom API call is made on
    an uncertain or invalid classification.
    """
    intent = raw.get("intent")
    confidence = _as_confidence(raw.get("confidence"))
    possible_intents = [i for i in raw.get("possible_intents") or [] if i in ALLOWED_INTENTS]

    if intent not in ALLOWED_INTENTS or confidence < threshold:
        return RouterResult(
            intent=None,
            confidence=confidence,
            needs_clarification=True,
            possible_intents=possible_intents,
            clarification_message=raw.get("clarification_question") or DEFAULT_CLARIFICATION_MESSAGE,
        )

    return RouterResult(
        intent=intent,
        confidence=confidence,
        needs_clarification=False,
        possible_intents=[],
        clarification_message=None,
    )


def _as_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
