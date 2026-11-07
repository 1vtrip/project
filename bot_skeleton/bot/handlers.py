import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import (
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
    ChatMemberUpdatedFilter,
    Command,
    CommandObject,
    CommandStart,
)
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.config import Config
from bot.interfaces import ChatRepository, GroupNotFound, ScheduleProvider, ScheduleUnavailable
from bot.views import ScheduleCb, View, render, schedule_keyboard

router = Router()

GROUP_RE = re.compile(r"\d{6}")
GROUP_CHATS = (ChatType.GROUP, ChatType.SUPERGROUP)

HELP_TEXT = (
    "👋 Я присылаю расписание БГУИР в беседу каждое утро.\n\n"
    "/setgroup <code>123456</code> — привязать беседу к группе (админы)\n"
    "/today — расписание на сегодня\n"
    "/stop — отключить рассылку (админы)\n"
    "/help — эта справка"
)


async def is_admin(message: Message, bot: Bot) -> bool:
    """В личке можно всё; в беседе — только админам, в том числе анонимным."""
    if message.chat.type == ChatType.PRIVATE:
        return True
    # Анонимный админ пишет от имени самой беседы
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if message.from_user is None:
        return False
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("setgroup"))
async def cmd_setgroup(
    message: Message,
    command: CommandObject,
    bot: Bot,
    repo: ChatRepository,
    schedule: ScheduleProvider,
    config: Config,
) -> None:
    group = (command.args or "").strip()
    if not GROUP_RE.fullmatch(group):
        await message.answer("Укажи номер группы из 6 цифр: <code>/setgroup 123456</code>")
        return
    if not await is_admin(message, bot):
        await message.answer("Менять группу могут только администраторы беседы.")
        return

    try:
        # заодно проверяем, что группа существует
        await schedule.day_message(group, datetime.now(config.tz).date())
    except GroupNotFound:
        await message.answer(f"Группа <b>{group}</b> не найдена в расписании БГУИР.")
        return
    except ScheduleUnavailable:
        pass  # проверить не можем — сохраняем, рассылка сама разберётся

    await repo.set_group(message.chat.id, group)
    await message.answer(
        f"✅ Беседа привязана к группе <b>{group}</b>.\n"
        "Буду присылать расписание каждое утро, кроме воскресенья."
    )


@router.message(Command("today"))
async def cmd_today(
    message: Message, repo: ChatRepository, schedule: ScheduleProvider, config: Config
) -> None:
    group = await repo.get_group(message.chat.id)
    if group is None:
        await message.answer("Сначала укажи группу: <code>/setgroup 123456</code>")
        return
    text = await render(View.TODAY, group, schedule, config.tz)
    await message.answer(text, reply_markup=schedule_keyboard(View.TODAY))


@router.callback_query(ScheduleCb.filter())
async def on_schedule_button(
    callback: CallbackQuery,
    callback_data: ScheduleCb,
    repo: ChatRepository,
    schedule: ScheduleProvider,
    config: Config,
) -> None:
    """Кнопки Сегодня/Завтра/Неделя: меняем текст того же сообщения, а не шлём новое."""
    message = callback.message
    if not isinstance(message, Message):  # сообщение слишком старое, Telegram его не отдаёт
        await callback.answer("Сообщение устарело, отправь /today", show_alert=True)
        return
    group = await repo.get_group(message.chat.id)
    if group is None:
        await callback.answer("Беседа не привязана к группе: /setgroup", show_alert=True)
        return
    # Отвечаем сразу, чтобы у нажавшего не крутились часики, пока ждём API
    await callback.answer()

    text = await render(callback_data.view, group, schedule, config.tz)
    try:
        await message.edit_text(text, reply_markup=schedule_keyboard(callback_data.view))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):  # нажали ту же вкладку ещё раз
            raise


@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot, repo: ChatRepository) -> None:
    if not await is_admin(message, bot):
        await message.answer("Отключить рассылку могут только администраторы беседы.")
        return
    await repo.remove_chat(message.chat.id)
    await message.answer("Рассылка отключена. Включить снова — /setgroup.")


@router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_bot_added(event: ChatMemberUpdated, bot: Bot) -> None:
    if event.chat.type in GROUP_CHATS:
        await bot.send_message(event.chat.id, HELP_TEXT)


@router.my_chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def on_bot_removed(event: ChatMemberUpdated, repo: ChatRepository) -> None:
    await repo.remove_chat(event.chat.id)


@router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message, repo: ChatRepository) -> None:
    """Группа стала супергруппой — у неё новый chat_id, переносим привязку."""
    group = await repo.get_group(message.chat.id)
    if group is not None:
        await repo.set_group(message.migrate_to_chat_id, group)
        await repo.remove_chat(message.chat.id)
