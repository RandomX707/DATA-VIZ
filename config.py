import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LiteLLM (OpenAI-compatible proxy)
    LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "")
    LITELLM_BASE_URL: str = os.getenv("LITELLM_BASE_URL", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-haiku-4-5")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))

    # Superset
    SUPERSET_URL: str = os.getenv("SUPERSET_URL", "http://localhost:8088")
    SUPERSET_TOKEN: str = os.getenv("SUPERSET_TOKEN", "")
    SUPERSET_USERNAME: str = os.getenv("SUPERSET_USERNAME", "admin")
    SUPERSET_PASSWORD: str = os.getenv("SUPERSET_PASSWORD", "admin")

    # Notifications (optional)
    SLACK_WEBHOOK_URL: str | None = os.getenv("SLACK_WEBHOOK_URL")
    NOTIFY_EMAIL_FROM: str | None = os.getenv("NOTIFY_EMAIL_FROM")
    NOTIFY_EMAIL_TO: str | None = os.getenv("NOTIFY_EMAIL_TO")
    NOTIFY_EMAIL_SMTP: str = os.getenv("NOTIFY_EMAIL_SMTP", "smtp.gmail.com")
    NOTIFY_EMAIL_PORT: int = int(os.getenv("NOTIFY_EMAIL_PORT", "587"))
    NOTIFY_EMAIL_PASSWORD: str | None = os.getenv("NOTIFY_EMAIL_PASSWORD")


config = Config()
