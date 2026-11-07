"""Что показать по команде или кнопке: сегодня, завтра или неделя."""
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.interfaces import GroupNotFound, ScheduleProvider, ScheduleUnavailable

WEEKDAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]


class View(str, Enum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEK = "week"


class ScheduleCb(CallbackData, prefix="sched"):
    view: View


BUTTONS = {View.TODAY: "Сегодня", View.TOMORROW: "Завтра", View.WEEK: "7 дней"}


def schedule_keyboard(current: View) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for view, title in BUTTONS.items():
        mark = "• " if view == current else ""  # подсвечиваем открытую вкладку
        kb.button(text=f"{mark}{title}", callback_data=ScheduleCb(view=view))
    return kb.as_markup()


def _no_lessons(view: View, day: date) -> str:
    if view == View.WEEK:
        return "В ближайшие 7 дней пар нет 🎉"
    when = "Сегодня" if view == View.TODAY else "Завтра"
    return f"{when}, в {WEEKDAYS_ACC[day.weekday()]} {day:%d.%m}, пар нет 🎉"


async def render(view: View, group: str, schedule: ScheduleProvider, tz: ZoneInfo) -> str:
    """Готовый текст для выбранной вкладки, включая тексты ошибок."""
    today = datetime.now(tz).date()
    try:
        if view == View.WEEK:
            day = today
            text = await schedule.week_message(group, today)  # 7 дней начиная с сегодня
        else:
            day = today if view == View.TODAY else today + timedelta(days=1)
            text = await schedule.day_message(group, day)
    except GroupNotFound:
        return "Группа больше не найдена в расписании. Проверь номер через /setgroup."
    except ScheduleUnavailable:
        return "Сайт БГУИР сейчас не отвечает, попробуй чуть позже 🙏"
    return text or _no_lessons(view, day)
