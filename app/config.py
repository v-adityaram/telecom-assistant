from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-06-01"

    telecom_api_base_url: str = ""
    telecom_api_key: str = ""

    intent_confidence_threshold: float = 0.80

    cors_allow_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
