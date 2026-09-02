from app.router.schemas import RouterResult
from app.tools.registry import TOOL_REGISTRY

ALLOWED_INTENTS = set(TOOL_REGISTRY.keys())

# Not a tool-registry entry — chat.py routes this to the LangGraph fallback
# (app/services/complex_flow.py) instead of execute_tool.
COMPLEX_INTENT = "COMPLEX"

# Only used when the model doesn't supply its own clarification_question.
DEFAULT_CLARIFICATION_MESSAGE = (
    "Happy to help — I can check your plan or profile, device details, balance, "
    "purchase history, or available offers. Which one would you like?"
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

    if intent == COMPLEX_INTENT:
        # A routing decision, not a single tool call — never gated behind the
        # threshold, and never offered as a clarification chip.
        return RouterResult(
            intent=COMPLEX_INTENT,
            confidence=confidence,
            needs_clarification=False,
            possible_intents=[],
            clarification_message=None,
        )

    possible_intents = [i for i in raw.get("possible_intents") or [] if i in ALLOWED_INTENTS]
    # The model often reports its leading guess as `intent` (low confidence) and
    # lists only the *other* reading in possible_intents — merge it back in so
    # the user sees every option and the follow-up turn can resolve to any of them.
    if possible_intents and intent in ALLOWED_INTENTS and intent not in possible_intents:
        possible_intents.insert(0, intent)

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
        scope=_as_scope(raw.get("scope")),
    )


def _as_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_scope(value: object) -> str:
    return value if value in ("full", "specific") else "full"
