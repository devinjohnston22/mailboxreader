import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str
    mailbox_id: str = "primary"
    live_folder: str = "inbox"
    history_start: str = "2020-01-01T00:00:00Z"
    history_end: str = ""
    high_value_amount: Decimal = Decimal("10000")
    high_value_currency: str = "USD"
    ai_enabled: bool = False
    ai_api_key: str = ""
    ai_model: str = "gpt-4.1-mini"

    @classmethod
    def from_env(cls):
        token = os.environ.get("API_TOKEN", "")
        if len(token) < 32:
            raise ValueError("API_TOKEN must contain at least 32 characters")
        return cls(
            database_url=os.environ["DATABASE_URL"], api_token=token,
            mailbox_id=os.getenv("MAILBOX_ID", "primary"), live_folder=os.getenv("LIVE_FOLDER", "inbox"),
            history_start=os.getenv("HISTORY_START", "2020-01-01T00:00:00Z"), history_end=os.getenv("HISTORY_END", ""),
            high_value_amount=Decimal(os.getenv("HIGH_VALUE_AMOUNT", "10000")),
            high_value_currency=os.getenv("HIGH_VALUE_CURRENCY", "USD"),
            ai_enabled=os.getenv("AI_ENABLED", "false").lower() == "true",
            ai_api_key=os.getenv("AI_API_KEY", ""), ai_model=os.getenv("AI_MODEL", "gpt-4.1-mini"),
        )
