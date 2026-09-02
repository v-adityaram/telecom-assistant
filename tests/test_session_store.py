from app.services.session_store import PendingClarification, clear_pending, get_pending, set_pending


def test_set_then_get_returns_pending_clarification():
    pending = PendingClarification(original_message="check my plan", possible_intents=["PROFILE", "OFFERS"])

    set_pending("session-1", pending)

    assert get_pending("session-1") == pending


def test_get_returns_none_for_unknown_session():
    assert get_pending("does-not-exist") is None


def test_clear_removes_pending_clarification():
    pending = PendingClarification(original_message="check my plan", possible_intents=["PROFILE"])
    set_pending("session-2", pending)

    clear_pending("session-2")

    assert get_pending("session-2") is None


def test_clear_on_unknown_session_is_a_no_op():
    clear_pending("never-set")
