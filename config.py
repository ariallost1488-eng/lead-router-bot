from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    ADMIN_TELEGRAM_IDS: str = ""
    POLL_INTERVAL_SECONDS: int = 60
    DATABASE_PATH: str = "leads_bot.db"
    DIALOGIAI_BASE_URL: str = "https://api.dialogiai.ru"

    @property
    def admin_ids(self) -> List[int]:
        if not self.ADMIN_TELEGRAM_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_TELEGRAM_IDS.split(",") if x.strip().isdigit()]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
