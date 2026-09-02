"""Deterministic answer-message templates, keyed by intent.

Kept template-based (no extra LLM call) to keep the fast path fast, per the
plan's "avoid unnecessary chains" rule. Field names match the real telecom
API response shapes observed live against the POC endpoints, nested under
the envelope's "data" key. Every accessor is defensive (.get with fallbacks)
so a missing field degrades the wording, never raises.
"""

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def render_answer_message(intent: str, envelope: dict | None) -> str:
    payload = (envelope or {}).get("data") or {}
    renderer = _RENDERERS.get(intent, _default)
    return renderer(payload)


# ---------- small formatting helpers ----------

def _money(amount, currency: str | None) -> str:
    if amount is None:
        return "unavailable"
    try:
        text = f"{float(amount):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        text = str(amount)
    symbol = CURRENCY_SYMBOLS.get(currency or "")
    return f"{symbol}{text}" if symbol else f"{text} {currency or ''}".strip()


def _date(value) -> str:
    # API dates are ISO ("2026-08-20T23:59:59+05:30") — the day is enough for a chat reply.
    return str(value)[:10] if value else "n/a"


def _yes_no(value) -> str:
    return "yes" if value else "no"


def _on_off(value) -> str:
    return "on" if value else "off"


# ---------- per-intent renderers ----------

def _profile(d: dict) -> str:
    plan = d.get("plan") or {}
    flags = d.get("serviceFlags") or {}
    plan_name = plan.get("planName", "your current plan")

    plan_bits = []
    if plan.get("price") is not None:
        plan_bits.append(_money(plan.get("price"), plan.get("currency")))
    if plan.get("validityDays") is not None:
        plan_bits.append(f"{plan['validityDays']} days")
    plan_desc = f"{plan_name} ({' / '.join(plan_bits)})" if plan_bits else plan_name

    lines = [
        f"You're on {plan_desc} — {d.get('subscriberType', 'plan type n/a')}, "
        f"{d.get('customerType', 'customer')}, status {d.get('status', 'unknown')}.",
        f"Circle: {d.get('telecomCircle', 'n/a')} · Active since {_date(d.get('activationDate'))}"
        f" · Auto-renew: {_on_off(plan.get('autoRenew'))}",
    ]
    if flags:
        lines.append(
            f"5G eligible: {_yes_no(flags.get('is5GEligible'))} · "
            f"International roaming: {_on_off(flags.get('internationalRoamingEnabled'))} · "
            f"DND: {_on_off(flags.get('dndEnabled'))}"
        )
    return "\n".join(lines)


def _device(d: dict) -> str:
    device = d.get("device") or {}
    sim = d.get("sim") or {}
    network = d.get("network") or {}

    name = f"{device.get('manufacturer', '')} {device.get('model', '')}".strip() or "device on file"
    descriptors = [x for x in [device.get("operatingSystem"), (device.get("deviceType") or "").lower()] if x]
    caps = []
    if device.get("networkCapability"):
        caps.append("/".join(device["networkCapability"]))
    if device.get("volteSupported"):
        caps.append("VoLTE")
    if device.get("wifiCallingSupported"):
        caps.append("Wi-Fi calling")

    first = f"Your registered device is a {name}"
    if descriptors:
        first += f" ({' '.join(descriptors)})"
    if caps:
        first += f" — {', '.join(caps)}"
    lines = [first + "."]

    if sim:
        sim_bits = [sim.get("simType"), sim.get("simStatus")]
        if sim.get("isEsim"):
            sim_bits.append("eSIM")
        lines.append(
            f"SIM: {', '.join(b for b in sim_bits if b) or 'n/a'} · "
            f"activated {_date(sim.get('activationDate'))}"
        )
    if network:
        lines.append(
            f"Network: {network.get('currentTechnology', 'n/a')} · "
            f"{network.get('roamingStatus', 'n/a')} ({network.get('lastKnownCircle', 'n/a')})"
        )
    if device.get("imei"):
        lines.append(f"IMEI: {device['imei']}")
    return "\n".join(lines)


def _balance(d: dict) -> str:
    wallet = d.get("mainWallet") or {}
    data = d.get("data") or {}
    voice = d.get("voice") or {}
    sms = d.get("sms") or {}
    addons = d.get("addOnBalances") or []

    lines = [
        f"Main balance: {_money(wallet.get('balance'), wallet.get('currency'))}"
        + (f" (valid till {_date(wallet['expiryDate'])})" if wallet.get("expiryDate") else "")
    ]
    if data.get("remainingMB") is not None:
        line = f"Data: {data['remainingMB']} MB left"
        if data.get("totalMB") is not None:
            line += f" of {data['totalMB']} MB"
        if data.get("dailyRemainingMB") is not None:
            line += f" ({data['dailyRemainingMB']} MB left today)"
        if data.get("expiryDate"):
            line += f" · expires {_date(data['expiryDate'])}"
        lines.append(line)
    if voice:
        line = f"Voice: {voice.get('planType', 'n/a')}"
        if voice.get("usedMinutes") is not None:
            line += f", {voice['usedMinutes']} min used"
        lines.append(line)
    if sms.get("remaining") is not None:
        line = f"SMS: {sms['remaining']} left"
        if sms.get("expiryDate"):
            line += f" · expires {_date(sms['expiryDate'])}"
        lines.append(line)
    if addons:
        parts = [
            f"{a.get('name', 'add-on')} ({a.get('remaining', 'n/a')}, till {_date(a.get('expiryDate'))})"
            for a in addons
        ]
        lines.append("Add-ons: " + "; ".join(parts))
    return "\n".join(lines)


def _purchase_history(d: dict) -> str:
    transactions = d.get("transactions") or []
    if not transactions:
        return "You have no recent purchases."
    currency = d.get("currency")
    # The API returns oldest-first; show newest first so "most recent" is actually on top.
    ordered = sorted(transactions, key=lambda t: str(t.get("purchasedAt", "")), reverse=True)

    lines = [f"Your recent purchases ({len(ordered)}), newest first:"]
    for i, t in enumerate(ordered, 1):
        line = f"{i}. {t.get('product', 'a purchase')} — {_money(t.get('amount'), currency)}"
        if t.get("paymentMethod"):
            line += f" via {t['paymentMethod']}"
        if t.get("purchasedAt"):
            line += f" on {_date(t['purchasedAt'])}"
        if t.get("validUntil"):
            line += f", valid till {_date(t['validUntil'])}"
        if t.get("status") and t["status"] != "Success":
            line += f" ({t['status']})"
        lines.append(line)
    return "\n".join(lines)


def _offers(d: dict) -> str:
    offers = d.get("offers") or []
    if not offers:
        return "There are no offers available right now."
    currency = d.get("currency")

    lines = [f"You have {len(offers)} offer{'s' if len(offers) != 1 else ''} available:"]
    for i, o in enumerate(offers, 1):
        line = f"{i}. {o.get('name', 'an offer')} — {_money(o.get('price'), currency)}"
        validity = o.get("validity") or {}
        if validity.get("amount") is not None:
            unit = str(validity.get("unit", "days")).lower()
            if validity["amount"] != 1 and not unit.endswith("s"):
                unit += "s"  # the API mixes "Day" and "Days"
            line += f", {validity['amount']} {unit}"
        if o.get("description"):
            line += f": {o['description']}"
        elif o.get("benefits"):
            line += f": {', '.join(o['benefits'])}"
        if o.get("isPersonalized"):
            line += " (personalized for you)"
        if o.get("isEligible") is False:
            line += " (not eligible)"
        lines.append(line)
    return "\n".join(lines)


def _default(_: dict) -> str:
    return "Here's what I found."


_RENDERERS = {
    "PROFILE": _profile,
    "DEVICE_DETAILS": _device,
    "BALANCE": _balance,
    "PURCHASE_HISTORY": _purchase_history,
    "OFFERS": _offers,
}
