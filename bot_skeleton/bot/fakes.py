"""Заглушки для разработки бота без БД и C++-модуля."""
from datetime import date

from bot.interfaces import GroupNotFound


class InMemoryChatRepository:
    def __init__(self) -> None:
        self._chats: dict[int, str] = {}

    async def set_group(self, chat_id: int, group: str) -> None:
        self._chats[chat_id] = group

    async def get_group(self, chat_id: int) -> str | None:
        return self._chats.get(chat_id)

    async def remove_chat(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)

    async def all_subscriptions(self) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for chat_id, group in self._chats.items():
            result.setdefault(group, []).append(chat_id)
        return result


class FakeScheduleProvider:
    """Любая 6-значная группа существует, кроме 000000."""

    async def day_message(self, group: str, day: date) -> str | None:
        if group == "000000":
            raise GroupNotFound(group)
        return (
            f"📅 <b>Расписание группы {group} на {day:%d.%m}</b>\n\n"
            "🕘 09:00–10:20 · <b>ООП</b> (ЛК) · 506-5\n"
            "🕥 10:35–11:55 · <b>Матанализ</b> (ПЗ) · 312-1"
        )

    async def week_message(self, group: str, start: date) -> str | None:
        return await self.day_message(group, start)
