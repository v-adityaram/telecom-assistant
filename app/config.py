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

    telecom_api_base_url: str = ""
    telecom_api_key: str = ""

    intent_confidence_threshold: float = 0.80
    # Lower bar for the follow-up turn after a clarification: the model is
    # choosing between 2-3 named candidates, not classifying from scratch.
    intent_followup_confidence_threshold: float = 0.60

    cors_allow_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
