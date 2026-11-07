import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import (
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
    ChatMemberUpdatedFilter,
    Command,
    CommandObject,
    CommandStart,
)
from aiogram.types import ChatMemberUpdated, Message

from bot.interfaces import ChatRepository, GroupNotFound, ScheduleProvider, ScheduleUnavailable

router = Router()

GROUP_RE = re.compile(r"\d{6}")
GROUP_CHATS = (ChatType.GROUP, ChatType.SUPERGROUP)

HELP_TEXT = (
    "👋 Я присылаю расписание БГУИР в беседу каждое утро.\n\n"
    "/setgroup <code>521704</code> — привязать беседу к группе (админы)\n"
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
) -> None:
    group = (command.args or "").strip()
    if not GROUP_RE.fullmatch(group):
        await message.answer("Укажи номер группы из 6 цифр: <code>/setgroup 521704</code>")
        return
    if not await is_admin(message, bot):
        await message.answer("Менять группу могут только администраторы беседы.")
        return

    try:
        await schedule.today_message(group)  # заодно проверяем, что группа существует
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
async def cmd_today(message: Message, repo: ChatRepository, schedule: ScheduleProvider) -> None:
    group = await repo.get_group(message.chat.id)
    if group is None:
        await message.answer("Сначала укажи группу: <code>/setgroup 521704</code>")
        return
    try:
        text = await schedule.today_message(group)
    except GroupNotFound:
        await message.answer("Группа больше не найдена в расписании. Проверь номер через /setgroup.")
        return
    except ScheduleUnavailable:
        await message.answer("Сайт БГУИР сейчас не отвечает, попробуй чуть позже 🙏")
        return
    await message.answer(text or "Сегодня пар нет 🎉")


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
