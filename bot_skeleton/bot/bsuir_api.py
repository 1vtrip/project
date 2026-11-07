"""Временный провайдер расписания на Python, напрямую к API БГУИР.

Нужен, чтобы тестировать бота на настоящих данных, пока нет C++-ядра
(Студент 2) и интеграции через subprocess (Студент 3). Потом его заменит
их реализация ScheduleProvider, а код бота не изменится.
"""
import asyncio
from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import aiohttp

from bot.interfaces import GroupNotFound, ScheduleUnavailable

API = "https://iis.bsuir.by/api/v1/schedule"
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
TYPE_EMOJI = {"ЛК": "📖", "ПЗ": "✏️", "ЛР": "🧪"}


def _parse_date(s: str | None) -> date | None:
    return datetime.strptime(s, "%d.%m.%Y").date() if s else None


def _week_for(day: date, today: date, current_week: int) -> int:
    """Учебная неделя (1-4) для любой даты: недели идут по кругу с понедельника."""
    shift = ((day - timedelta(days=day.weekday())) - (today - timedelta(days=today.weekday()))).days // 7
    return (current_week - 1 + shift) % 4 + 1


def _lessons_on(data: dict, day: date, week: int) -> list[dict]:
    def matches(ls: dict) -> bool:
        if ls.get("dateLesson"):  # разовое занятие на конкретную дату
            return _parse_date(ls["dateLesson"]) == day
        if week not in (ls.get("weekNumber") or []):
            return False
        start = _parse_date(ls.get("startLessonDate"))
        end = _parse_date(ls.get("endLessonDate"))
        return (start is None or start <= day) and (end is None or day <= end)

    day_lessons = (data.get("schedules") or {}).get(WEEKDAYS[day.weekday()], [])
    return sorted(filter(matches, day_lessons), key=lambda ls: ls["startLessonTime"])


def _format_lesson(ls: dict) -> str:
    abbr = ls.get("lessonTypeAbbrev") or ""
    line = (
        f"{TYPE_EMOJI.get(abbr, '🔹')} {ls['startLessonTime']}–{ls['endLessonTime']} · "
        f"<b>{escape(ls.get('subject') or '')}</b>"
    )
    if abbr:
        line += f" ({escape(abbr)})"
    if ls.get("auditories"):
        line += " · " + escape(", ".join(ls["auditories"]))
    if ls.get("numSubgroup"):
        line += f" · подгр. {ls['numSubgroup']}"
    teachers = [f"{e['lastName']} {e['firstName'][:1]}.{e['middleName'][:1]}."
                for e in ls.get("employees") or [] if e.get("lastName")]
    if teachers:
        line += "\n      👤 " + escape(", ".join(teachers))
    if ls.get("note"):
        line += "\n      📝 " + escape(ls["note"])
    return line


class BsuirApiScheduleProvider:
    def __init__(self, tz: ZoneInfo) -> None:
        self._tz = tz
        self._timeout = aiohttp.ClientTimeout(total=15)

    async def _get_json(self, session: aiohttp.ClientSession, url: str, **params):
        async with session.get(url, params=params) as resp:
            if resp.status == 404:
                raise GroupNotFound(params.get("studentGroup"))
            resp.raise_for_status()
            return await resp.json()

    async def _fetch(self, group: str) -> tuple[dict, int]:
        """Расписание группы и номер текущей учебной недели."""
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                week = await self._get_json(session, f"{API}/current-week")
                data = await self._get_json(session, API, studentGroup=group)
        except GroupNotFound:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise ScheduleUnavailable(repr(e)) from e
        return data, int(week)

    async def day_message(self, group: str, day: date) -> str | None:
        data, current_week = await self._fetch(group)
        week = _week_for(day, datetime.now(self._tz).date(), current_week)
        lessons = _lessons_on(data, day, week)
        if not lessons:
            return None
        return "\n".join([
            f"📅 <b>Расписание группы {escape(group)}</b>",
            f"{WEEKDAYS[day.weekday()]}, {day:%d.%m} · {week}-я неделя",
            "",
            *map(_format_lesson, lessons),
        ])

    async def week_message(self, group: str, start: date) -> str | None:
        data, current_week = await self._fetch(group)
        today = datetime.now(self._tz).date()
        blocks = []
        for i in range(7):
            day = start + timedelta(days=i)
            if day.weekday() == 6:  # воскресенье
                continue
            week = _week_for(day, today, current_week)
            lessons = _lessons_on(data, day, week)
            if lessons:
                blocks.append(
                    f"<b>{WEEKDAYS[day.weekday()]}, {day:%d.%m}</b> · {week}-я неделя\n"
                    + "\n".join(map(_format_lesson, lessons))
                )
        if not blocks:
            return None
        end = start + timedelta(days=6)
        header = f"🗓 <b>Группа {escape(group)} · 7 дней</b>\n{start:%d.%m}–{end:%d.%m}"
        return "\n\n".join([header, *blocks])
