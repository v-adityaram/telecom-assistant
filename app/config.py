from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # Azure OpenAI unified v1 API surface: endpoint ends in /openai/v1,
    # deployment is passed as the chat completions "model" value.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_realtime_deployment: str = ""
    # Optional: name of a deployed transcription model (e.g. whisper), used
    # only to show a live transcript of what the caller said. Omit if unset.
    azure_openai_transcribe_deployment: str = ""
    # "far_field" for a laptop/desk mic (caller not wearing a headset — the
    # common case, and the one background noise reports have come from),
    # "near_field" for a headset/earbuds mic close to the mouth.
    realtime_noise_reduction_mode: str = "far_field"
    # server_vad sensitivity: 0.0-1.0, higher = requires louder/clearer audio
    # before treating it as speech. Raised from the API's 0.5 default after
    # live testing in a loud environment still triggered on background noise.
    # Configurable (not hardcoded) since this needs real-environment tuning.
    realtime_vad_threshold: float = 0.7

    # Self-hosted coturn TURN relay (see deploy/setup_vm.sh) — fixes voice on
    # networks that block outbound UDP/WebRTC entirely (e.g. corporate
    # proxies like Zscaler), which no STUN server can work around, since
    # TURN relays over a plain outbound TCP/TLS connection that looks like
    # ordinary HTTPS. Empty secret disables it — voice falls back to
    # STUN-only exactly as before, no error either way.
    turn_shared_secret: str = ""
    turn_domain: str = ""

    telecom_api_base_url: str = ""
    telecom_api_key: str = ""

    # Conversation persistence (F-004). Partition key /mobileNumber, one
    # document per conversation. Empty connection string disables history —
    # chat/voice work exactly as before, no error.
    cosmos_connection_string: str = ""
    cosmos_database: str = "telecom-poc-db"
    cosmos_container: str = "conversations"

    intent_confidence_threshold: float = 0.80
    # Lower bar for the follow-up turn after a clarification: the model is
    # choosing between 2-3 named candidates, not classifying from scratch.
    intent_followup_confidence_threshold: float = 0.60

    cors_allow_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
