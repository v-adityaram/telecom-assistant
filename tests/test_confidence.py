from app.router.confidence import DEFAULT_CLARIFICATION_MESSAGE, build_router_result

THRESHOLD = 0.80


def test_high_confidence_known_intent_is_answered():
    raw = {"intent": "BALANCE", "confidence": 0.98}

    result = build_router_result(raw, THRESHOLD)

    assert result.intent == "BALANCE"
    assert result.needs_clarification is False
    assert result.possible_intents == []
    assert result.clarification_message is None


def test_low_confidence_triggers_clarification_without_intent():
    raw = {
        "intent": "PROFILE",
        "confidence": 0.55,
        "possible_intents": ["PROFILE", "OFFERS"],
        "clarification_question": "Do you mean your current plan or available plans?",
    }

    result = build_router_result(raw, THRESHOLD)

    assert result.intent is None
    assert result.needs_clarification is True
    assert result.possible_intents == ["PROFILE", "OFFERS"]
    assert result.clarification_message == "Do you mean your current plan or available plans?"


def test_missing_clarification_question_uses_default_message():
    raw = {"intent": "PROFILE", "confidence": 0.4, "possible_intents": ["PROFILE"]}

    result = build_router_result(raw, THRESHOLD)

    assert result.clarification_message == DEFAULT_CLARIFICATION_MESSAGE


def test_unknown_intent_triggers_clarification():
    raw = {"intent": "UNKNOWN", "confidence": 0.99}

    result = build_router_result(raw, THRESHOLD)

    assert result.intent is None
    assert result.needs_clarification is True


def test_hallucinated_intent_is_rejected_even_at_high_confidence():
    raw = {"intent": "DELETE_ACCOUNT", "confidence": 0.99}

    result = build_router_result(raw, THRESHOLD)

    assert result.intent is None
    assert result.needs_clarification is True


def test_possible_intents_filters_out_invalid_entries():
    raw = {
        "intent": "PROFILE",
        "confidence": 0.5,
        "possible_intents": ["PROFILE", "NOT_REAL", "OFFERS"],
    }

    result = build_router_result(raw, THRESHOLD)

    assert result.possible_intents == ["PROFILE", "OFFERS"]


def test_non_numeric_confidence_defaults_to_zero():
    raw = {"intent": "BALANCE", "confidence": "not-a-number"}

    result = build_router_result(raw, THRESHOLD)

    assert result.confidence == 0.0
    assert result.needs_clarification is True


def test_confidence_is_clamped_to_valid_range():
    raw = {"intent": "BALANCE", "confidence": 5.0}

    result = build_router_result(raw, THRESHOLD)

    assert result.confidence == 1.0
