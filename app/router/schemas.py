from pydantic import BaseModel


class RouterResult(BaseModel):
    intent: str | None
    confidence: float
    needs_clarification: bool
    possible_intents: list[str] = []
    clarification_message: str | None = None
    # "full" (default template) or "specific" (narrow, synthesized answer).
    # Only meaningful when intent is a resolved single-lookup intent.
    scope: str = "full"
