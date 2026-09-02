"""Deterministic answer-message templates, keyed by intent.

Kept template-based (no extra LLM call) to keep the fast path fast, per the
plan's "avoid unnecessary chains" rule. Field names match the real telecom
API response shapes observed live against the POC endpoints, nested under
the envelope's "data" key.
"""


def render_answer_message(intent: str, envelope: dict | None) -> str:
    payload = (envelope or {}).get("data") or {}
    renderer = _RENDERERS.get(intent, _default)
    return renderer(payload)


def _profile(d: dict) -> str:
    plan_name = d.get("plan", {}).get("planName", "your current plan")
    status = d.get("status", "unknown")
    return f"You're on {plan_name}, and your account status is {status}."


def _device(d: dict) -> str:
    device = d.get("device", {})
    name = f"{device.get('manufacturer', '')} {device.get('model', '')}".strip()
    sim_status = d.get("sim", {}).get("simStatus", "unknown")
    return f"Your registered device is a {name or 'device on file'}, SIM status: {sim_status}."


def _balance(d: dict) -> str:
    wallet = d.get("mainWallet", {})
    balance, currency = wallet.get("balance"), wallet.get("currency", "")
    balance_str = f"{balance} {currency}".strip() if balance is not None else "unavailable"
    message = f"Your main balance is {balance_str}."

    remaining_mb = d.get("data", {}).get("remainingMB")
    if remaining_mb is not None:
        message += f" You have {remaining_mb} MB of data remaining."
    return message


def _purchase_history(d: dict) -> str:
    transactions = d.get("transactions") or []
    if not transactions:
        return "You have no recent purchases."
    latest = transactions[0]
    currency = d.get("currency", "")
    return (
        f"Your most recent purchase was {latest.get('product', 'a purchase')} "
        f"for {latest.get('amount')} {currency}.".strip()
    )


def _offers(d: dict) -> str:
    offers = d.get("offers") or []
    if not offers:
        return "There are no offers available right now."
    top = offers[0]
    currency = d.get("currency", "")
    return (
        f"You have {len(offers)} offer(s) available, e.g. {top.get('name', 'an offer')} "
        f"for {top.get('price')} {currency}.".strip()
    )


def _default(_: dict) -> str:
    return "Here's what I found."


_RENDERERS = {
    "PROFILE": _profile,
    "DEVICE_DETAILS": _device,
    "BALANCE": _balance,
    "PURCHASE_HISTORY": _purchase_history,
    "OFFERS": _offers,
}
