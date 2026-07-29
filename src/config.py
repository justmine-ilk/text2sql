import os
from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App Config
    app_name: str = "AI Agent Text-to-SQL Analytics"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    cors_origins: str = "*"

    # LLM (Google AI Studio)
    google_api_key: str = "AIzaSyA03lRiz9bhoLIcTMxP4orQWpfbtXICLbw"
    gemini_model: str = "gemini-2.5-flash"
    llm_temperature: float = 0.1

    # Database
    database_url: str = "sqlite:///./data/online_retail.db"
    csv_data_path: str = "./data/synthetic_online_retail_data.csv"

    # Security & Cost Limits
    jwt_secret: str = "super-secret-key-ai20k-text2sql-2026"
    max_bytes_scanned_limit: int = 100000000  # 100MB
    max_retry_attempts: int = 3

    # AI Logging (BTC AI20K)
    ai_log_server: str = "https://ai-logs.note.transformerlabs.ai/api/ingest"
    ai_log_api_key: str = "ai20k_C2NEb0Z15_UnSB3nDCdFsUAMiLTJyPqn"
    ai_log_dir: str = ".ai-log"


@lru_cache
def get_settings() -> Settings:
    return Settings()
