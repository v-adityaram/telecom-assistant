from app.services.response import render_answer_message

# Shapes mirror real responses observed live against the telecom POC API.
PROFILE_ENVELOPE = {
    "data": {
        "status": "Active",
        "plan": {"planId": "PREPAID-299", "planName": "Unlimited 5G Value 299"},
    }
}

DEVICE_ENVELOPE = {
    "data": {
        "device": {"manufacturer": "OnePlus", "model": "Nord CE 4"},
        "sim": {"simStatus": "Active"},
    }
}

BALANCE_ENVELOPE = {
    "data": {
        "mainWallet": {"balance": 102.5, "currency": "INR"},
        "data": {"remainingMB": 3485},
    }
}

PURCHASE_HISTORY_ENVELOPE = {
    "data": {
        "currency": "INR",
        "transactions": [
            {"product": "Unlimited 5G Value 299", "amount": 305.0},
            {"product": "1 GB Data Booster", "amount": 25.0},
        ],
    }
}

OFFERS_ENVELOPE = {
    "data": {
        "currency": "INR",
        "offers": [
            {"name": "Unlimited Value 239", "price": 248.0},
            {"name": "6 GB Data Booster", "price": 70.0},
        ],
    }
}


def test_profile_message_includes_plan_and_status():
    message = render_answer_message("PROFILE", PROFILE_ENVELOPE)
    assert "Unlimited 5G Value 299" in message
    assert "Active" in message


def test_device_message_includes_manufacturer_model_and_sim_status():
    message = render_answer_message("DEVICE_DETAILS", DEVICE_ENVELOPE)
    assert "OnePlus Nord CE 4" in message
    assert "Active" in message


def test_balance_message_includes_amount_currency_and_data_remaining():
    message = render_answer_message("BALANCE", BALANCE_ENVELOPE)
    assert "102.5 INR" in message
    assert "3485 MB" in message


def test_purchase_history_message_uses_most_recent_transaction():
    message = render_answer_message("PURCHASE_HISTORY", PURCHASE_HISTORY_ENVELOPE)
    assert "Unlimited 5G Value 299" in message
    assert "305.0" in message


def test_purchase_history_message_handles_empty_transactions():
    message = render_answer_message("PURCHASE_HISTORY", {"data": {"transactions": []}})
    assert "no recent purchases" in message


def test_offers_message_includes_count_and_top_offer():
    message = render_answer_message("OFFERS", OFFERS_ENVELOPE)
    assert "2 offer(s)" in message
    assert "Unlimited Value 239" in message


def test_offers_message_handles_empty_offers():
    message = render_answer_message("OFFERS", {"data": {"offers": []}})
    assert "no offers available" in message


def test_unknown_intent_uses_default_message():
    assert render_answer_message("SOMETHING_ELSE", {"data": {}}) == "Here's what I found."


def test_handles_missing_envelope():
    message = render_answer_message("BALANCE", None)
    assert "unavailable" in message
