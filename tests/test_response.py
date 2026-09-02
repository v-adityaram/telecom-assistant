from app.services.response import render_answer_message

# Shapes mirror real responses observed live against the telecom POC API.
PROFILE_ENVELOPE = {
    "data": {
        "status": "Active",
        "subscriberType": "Prepaid",
        "customerType": "Individual",
        "telecomCircle": "Delhi",
        "activationDate": "2024-11-15",
        "plan": {
            "planId": "PREPAID-299",
            "planName": "Unlimited 5G Value 299",
            "price": 259.0,
            "currency": "INR",
            "validityDays": 28,
            "autoRenew": False,
        },
        "serviceFlags": {"is5GEligible": True, "internationalRoamingEnabled": False, "dndEnabled": False},
    }
}

DEVICE_ENVELOPE = {
    "data": {
        "device": {
            "imei": "350000000000003",
            "manufacturer": "OnePlus",
            "model": "Nord CE 4",
            "deviceType": "Smartphone",
            "operatingSystem": "Android",
            "networkCapability": ["2G", "4G", "5G"],
            "volteSupported": True,
            "wifiCallingSupported": True,
        },
        "sim": {"simType": "Nano SIM", "simStatus": "Active", "isEsim": False, "activationDate": "2024-11-15"},
        "network": {"currentTechnology": "5G NSA", "roamingStatus": "Home Network", "lastKnownCircle": "Delhi"},
    }
}

BALANCE_ENVELOPE = {
    "data": {
        "mainWallet": {"balance": 102.5, "currency": "INR", "expiryDate": "2026-11-15"},
        "data": {"totalMB": 5632, "remainingMB": 3485, "dailyRemainingMB": 1250, "expiryDate": "2026-08-20T23:59:59+05:30"},
        "voice": {"planType": "Unlimited", "usedMinutes": 217},
        "sms": {"remaining": 76, "expiryDate": "2026-08-20T23:59:59+05:30"},
        "addOnBalances": [
            {"name": "Unlimited 5G Data", "remaining": "Unlimited", "expiryDate": "2026-08-20T23:59:59+05:30"},
        ],
    }
}

PURCHASE_HISTORY_ENVELOPE = {
    "data": {
        "currency": "INR",
        # Oldest first, exactly as the live API returns it.
        "transactions": [
            {"product": "Unlimited 5G Value 299", "amount": 305.0, "paymentMethod": "UPI", "purchasedAt": "2026-07-24T18:42:10+05:30", "status": "Success"},
            {"product": "1 GB Data Booster", "amount": 25.0, "paymentMethod": "Main Balance", "purchasedAt": "2026-08-01T09:15:30+05:30", "status": "Success"},
        ],
    }
}

OFFERS_ENVELOPE = {
    "data": {
        "currency": "INR",
        "offers": [
            {
                "name": "Unlimited Value 239",
                "description": "1.5 GB/day, unlimited voice and 100 SMS/day.",
                "price": 248.0,
                "validity": {"amount": 30, "unit": "Days"},
                "isPersonalized": True,
                "isEligible": True,
            },
            {"name": "6 GB Data Booster", "price": 70.0, "validity": {"amount": 34, "unit": "Days"}, "benefits": ["6 GB high-speed data"]},
        ],
    }
}


def test_profile_message_includes_plan_price_validity_and_status():
    message = render_answer_message("PROFILE", PROFILE_ENVELOPE)
    assert "Unlimited 5G Value 299" in message
    assert "₹259" in message
    assert "28 days" in message
    assert "status Active" in message
    assert "5G eligible: yes" in message


def test_profile_message_survives_minimal_payload():
    message = render_answer_message("PROFILE", {"data": {"plan": {"planName": "Basic"}, "status": "Active"}})
    assert "Basic" in message
    assert "Active" in message


def test_device_message_lists_model_capabilities_sim_and_imei():
    message = render_answer_message("DEVICE_DETAILS", DEVICE_ENVELOPE)
    assert "OnePlus Nord CE 4" in message
    assert "2G/4G/5G" in message
    assert "VoLTE" in message
    assert "Nano SIM, Active" in message
    assert "IMEI: 350000000000003" in message


def test_balance_message_breaks_down_wallet_data_voice_sms_and_addons():
    message = render_answer_message("BALANCE", BALANCE_ENVELOPE)
    assert "Main balance: ₹102.5" in message
    assert "valid till 2026-11-15" in message
    assert "3485 MB left of 5632 MB" in message
    assert "1250 MB left today" in message
    assert "Voice: Unlimited, 217 min used" in message
    assert "SMS: 76 left" in message
    assert "Unlimited 5G Data (Unlimited, till 2026-08-20)" in message


def test_purchase_history_lists_all_transactions_newest_first():
    message = render_answer_message("PURCHASE_HISTORY", PURCHASE_HISTORY_ENVELOPE)
    lines = message.split("\n")
    assert lines[0] == "Your recent purchases (2), newest first:"
    assert lines[1].startswith("1. 1 GB Data Booster — ₹25 via Main Balance on 2026-08-01")
    assert lines[2].startswith("2. Unlimited 5G Value 299 — ₹305 via UPI on 2026-07-24")


def test_purchase_history_message_handles_empty_transactions():
    message = render_answer_message("PURCHASE_HISTORY", {"data": {"transactions": []}})
    assert "no recent purchases" in message


def test_offers_message_lists_every_offer_with_price_validity_and_description():
    message = render_answer_message("OFFERS", OFFERS_ENVELOPE)
    lines = message.split("\n")
    assert lines[0] == "You have 2 offers available:"
    assert lines[1] == "1. Unlimited Value 239 — ₹248, 30 days: 1.5 GB/day, unlimited voice and 100 SMS/day. (personalized for you)"
    assert lines[2] == "2. 6 GB Data Booster — ₹70, 34 days: 6 GB high-speed data"


def test_offers_message_flags_ineligible_offers():
    envelope = {"data": {"currency": "INR", "offers": [{"name": "Roaming Pack", "price": 99, "isEligible": False}]}}
    message = render_answer_message("OFFERS", envelope)
    assert "1 offer available" in message
    assert "(not eligible)" in message


def test_offers_message_handles_empty_offers():
    message = render_answer_message("OFFERS", {"data": {"offers": []}})
    assert "no offers available" in message


def test_non_inr_currency_falls_back_to_code():
    envelope = {"data": {"mainWallet": {"balance": 12.5, "currency": "ZAR"}}}
    assert "12.5 ZAR" in render_answer_message("BALANCE", envelope)


def test_unknown_intent_uses_default_message():
    assert render_answer_message("SOMETHING_ELSE", {"data": {}}) == "Here's what I found."


def test_handles_missing_envelope():
    message = render_answer_message("BALANCE", None)
    assert "unavailable" in message
