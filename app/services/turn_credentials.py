import base64
import hashlib
import hmac
import time

from app.config import get_settings

# Standard coturn REST API credential scheme (RFC 5766 TURN + the
# widely-used time-limited-credential convention coturn implements via
# `use-auth-secret`): username is an expiry timestamp, credential is an
# HMAC-SHA1 of that username under the shared secret. The secret itself
# never leaves this backend — only the derived, time-limited pair does,
# same trust model as the Azure OpenAI ephemeral token in realtime.py.
DEFAULT_TTL_SECONDS = 3600


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.turn_shared_secret and settings.turn_domain)


def generate_turn_credentials(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict | None:
    settings = get_settings()
    if not is_enabled():
        return None

    username = str(int(time.time()) + ttl_seconds)
    digest = hmac.new(settings.turn_shared_secret.encode(), username.encode(), hashlib.sha1).digest()
    credential = base64.b64encode(digest).decode()

    return {
        "urls": [f"turns:{settings.turn_domain}:5349?transport=tcp"],
        "username": username,
        "credential": credential,
    }
