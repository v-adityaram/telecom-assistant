import base64
import hashlib
import hmac
import time

from app.config import get_settings
from app.services import turn_credentials


def test_disabled_when_secret_or_domain_missing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "turn_shared_secret", "")
    monkeypatch.setattr(settings, "turn_domain", "turn.example.com")
    assert turn_credentials.is_enabled() is False
    assert turn_credentials.generate_turn_credentials() is None

    monkeypatch.setattr(settings, "turn_shared_secret", "shh")
    monkeypatch.setattr(settings, "turn_domain", "")
    assert turn_credentials.is_enabled() is False
    assert turn_credentials.generate_turn_credentials() is None


def test_generates_valid_hmac_credential(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "turn_shared_secret", "shh")
    monkeypatch.setattr(settings, "turn_domain", "turn.example.com")

    before = int(time.time())
    creds = turn_credentials.generate_turn_credentials(ttl_seconds=60)
    after = int(time.time())

    assert creds is not None
    assert creds["urls"] == ["turns:turn.example.com:5349?transport=tcp"]

    username_ts = int(creds["username"])
    assert before + 60 <= username_ts <= after + 60

    expected_digest = hmac.new(b"shh", creds["username"].encode(), hashlib.sha1).digest()
    expected_credential = base64.b64encode(expected_digest).decode()
    assert creds["credential"] == expected_credential


def test_default_ttl_is_one_hour(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "turn_shared_secret", "shh")
    monkeypatch.setattr(settings, "turn_domain", "turn.example.com")

    before = int(time.time())
    creds = turn_credentials.generate_turn_credentials()
    username_ts = int(creds["username"])

    assert 3590 <= username_ts - before <= 3610
