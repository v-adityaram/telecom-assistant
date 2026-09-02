import pytest

from app.router import intent_router


@pytest.mark.asyncio
async def test_route_intent_passes_candidates_and_applies_threshold(monkeypatch):
    captured = {}

    async def fake_classify_intent(message, candidate_intents=None):
        captured["message"] = message
        captured["candidate_intents"] = candidate_intents
        return {"intent": "OFFERS", "confidence": 0.9}

    monkeypatch.setattr(intent_router, "classify_intent", fake_classify_intent)

    result = await intent_router.route_intent("the available ones", candidate_intents=["PROFILE", "OFFERS"])

    assert captured["message"] == "the available ones"
    assert captured["candidate_intents"] == ["PROFILE", "OFFERS"]
    assert result.intent == "OFFERS"
    assert result.needs_clarification is False


@pytest.mark.asyncio
async def test_route_intent_below_threshold_needs_clarification(monkeypatch):
    async def fake_classify_intent(message, candidate_intents=None):
        return {"intent": "PROFILE", "confidence": 0.5, "possible_intents": ["PROFILE", "OFFERS"]}

    monkeypatch.setattr(intent_router, "classify_intent", fake_classify_intent)

    result = await intent_router.route_intent("check my plan")

    assert result.intent is None
    assert result.needs_clarification is True
    assert result.possible_intents == ["PROFILE", "OFFERS"]


@pytest.mark.asyncio
async def test_followup_turn_uses_lower_threshold(monkeypatch):
    async def fake_classify_intent(message, candidate_intents=None):
        return {"intent": "OFFERS", "confidence": 0.7}

    monkeypatch.setattr(intent_router, "classify_intent", fake_classify_intent)

    open_result = await intent_router.route_intent("the available ones")
    followup_result = await intent_router.route_intent("the available ones", candidate_intents=["PROFILE", "OFFERS"])

    assert open_result.needs_clarification is True  # 0.7 < 0.80 open threshold
    assert followup_result.needs_clarification is False  # 0.7 >= 0.60 follow-up threshold
    assert followup_result.intent == "OFFERS"
