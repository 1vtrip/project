import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import Config
from bot.interfaces import ChatRepository, GroupNotFound, ScheduleProvider, ScheduleUnavailable
from bot.views import View, schedule_keyboard

log = logging.getLogger(__name__)


async def send_daily(
    bot: Bot, repo: ChatRepository, schedule: ScheduleProvider, tz: ZoneInfo
) -> None:
    today = datetime.now(tz).date()
    subscriptions = await repo.all_subscriptions()
    log.info("Утренняя рассылка: %d групп", len(subscriptions))

    for group, chat_ids in subscriptions.items():
        try:
            text = await schedule.day_message(group, today)  # один вызов C++ на группу
        except (GroupNotFound, ScheduleUnavailable) as e:
            log.warning("Группа %s пропущена: %r", group, e)
            continue
        if not text:
            continue  # пар нет — не спамим

        for chat_id in chat_ids:
            await _safe_send(bot, repo, chat_id, text)
            await asyncio.sleep(0.05)  # держимся ниже лимита Telegram ~30 сообщений/с


async def _safe_send(bot: Bot, repo: ChatRepository, chat_id: int, text: str) -> None:
    keyboard = schedule_keyboard(View.TODAY)
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramForbiddenError:
        log.info("Бота удалили из %s — убираем подписку", chat_id)
        await repo.remove_chat(chat_id)
    except TelegramBadRequest as e:
        log.error("Не удалось отправить в %s: %s", chat_id, e)


def setup_scheduler(
    bot: Bot, repo: ChatRepository, schedule: ScheduleProvider, config: Config
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.tz)
    scheduler.add_job(
        send_daily,
        CronTrigger(
            day_of_week="mon-sat",
            hour=config.send_hour,
            minute=config.send_minute,
            timezone=config.tz,
        ),
        kwargs={"bot": bot, "repo": repo, "schedule": schedule, "tz": config.tz},
        id="daily_schedule",
        misfire_grace_time=600,  # если бот был недоступен, догоняем в течение 10 минут
        coalesce=True,
    )
    return scheduler
