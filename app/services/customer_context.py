from pydantic import BaseModel


class CustomerContext(BaseModel):
    mobile_number: str


def get_customer_context(mobile_number: str) -> CustomerContext:
    """Builds the authorized customer context for a request.

    Callers (chat/voice endpoints) must source mobile_number from the
    authenticated session, never from model/user-supplied text. Real
    session-backed authentication is wired in during Phase 11; for now
    this is the single seam tools depend on so that wiring is a
    localized change later.
    """
    return CustomerContext(mobile_number=mobile_number)
