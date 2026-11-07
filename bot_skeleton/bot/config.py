import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    tz: ZoneInfo
    send_hour: int
    send_minute: int


def load_config() -> Config:
    load_dotenv()  # подхватываем .env из текущей папки, если он есть
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана")
    return Config(
        bot_token=token,
        # Не называем переменную TZ: она влияет на время всего процесса
        tz=ZoneInfo(os.getenv("BOT_TZ", "Europe/Minsk")),
        send_hour=int(os.getenv("SEND_HOUR", "7")),
        send_minute=int(os.getenv("SEND_MINUTE", "0")),
    )
