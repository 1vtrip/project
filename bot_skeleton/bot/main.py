import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import load_config
from bot.bsuir_api import BsuirApiScheduleProvider
from bot.fakes import InMemoryChatRepository
from bot.handlers import router
from bot.scheduler import setup_scheduler


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # TODO: заменить на реальные реализации Студента 3 (PostgreSQL и C++ через subprocess)
    repo = InMemoryChatRepository()
    schedule = BsuirApiScheduleProvider(config.tz)  # временно: Python напрямую к API

    # Всё, что передано в Dispatcher, aiogram подставит в хендлеры по имени аргумента
    dp = Dispatcher(repo=repo, schedule=schedule, config=config)
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="today", description="Расписание на сегодня"),
        BotCommand(command="setgroup", description="Привязать беседу к группе"),
        BotCommand(command="stop", description="Отключить рассылку"),
        BotCommand(command="help", description="Справка"),
    ])

    scheduler = setup_scheduler(bot, repo, schedule, config)
    scheduler.start()
    try:
        # resolve_used_update_types включает my_chat_member — без него не узнаем о добавлении в беседу
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
