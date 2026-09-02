from pydantic import BaseModel


class PendingClarification(BaseModel):
    original_message: str
    possible_intents: list[str]


# In-memory only, per the plan: acceptable for the POC, not durable across
# restarts or multiple workers. Move to Redis only if that becomes necessary.
_PENDING: dict[str, PendingClarification] = {}


def get_pending(session_id: str) -> PendingClarification | None:
    return _PENDING.get(session_id)


def set_pending(session_id: str, pending: PendingClarification) -> None:
    _PENDING[session_id] = pending


def clear_pending(session_id: str) -> None:
    _PENDING.pop(session_id, None)
