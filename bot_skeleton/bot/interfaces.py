"""Контракты между ботом и остальными частями проекта.

Бот зависит только от этих интерфейсов. Пока Студенты 2 и 3 делают
C++-ядро и PostgreSQL, бот работает на заглушках из fakes.py.
Потом заглушки заменяются реальными классами, а код бота не меняется.
"""
from typing import Protocol


class GroupNotFound(Exception):
    """API БГУИР не знает такую группу."""


class ScheduleUnavailable(Exception):
    """API недоступно, таймаут или C++-модуль упал."""


class ChatRepository(Protocol):
    """Хранилище привязок беседа -> группа (реализует Студент 3, asyncpg)."""

    async def set_group(self, chat_id: int, group: str) -> None: ...

    async def get_group(self, chat_id: int) -> str | None: ...

    async def remove_chat(self, chat_id: int) -> None: ...

    async def all_subscriptions(self) -> dict[str, list[int]]:
        """Возвращает {номер группы: [chat_id, ...]}, чтобы дёргать C++ один раз на группу."""
        ...


class ScheduleProvider(Protocol):
    """Расписание на сегодня (Студент 3 вызывает C++ через subprocess и оформляет текст)."""

    async def today_message(self, group: str) -> str | None:
        """Готовый HTML-текст для Telegram или None, если сегодня пар нет.

        Raises:
            GroupNotFound: группы не существует.
            ScheduleUnavailable: расписание сейчас не получить.
        """
        ...
