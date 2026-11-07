"""Временный провайдер расписания на Python, напрямую к API БГУИР.

Нужен, чтобы тестировать бота на настоящих данных, пока нет C++-ядра
(Студент 2) и интеграции через subprocess (Студент 3). Потом его заменит
их реализация ScheduleProvider, а код бота не изменится.
"""
import asyncio
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

import aiohttp

from bot.interfaces import GroupNotFound, ScheduleUnavailable

API = "https://iis.bsuir.by/api/v1/schedule"
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
TYPE_EMOJI = {"ЛК": "📖", "ПЗ": "✏️", "ЛР": "🧪"}


def _parse_date(s: str | None) -> date | None:
    return datetime.strptime(s, "%d.%m.%Y").date() if s else None


def _is_today(lesson: dict, today: date, week: int) -> bool:
    # Разовое занятие на конкретную дату
    if lesson.get("dateLesson"):
        return _parse_date(lesson["dateLesson"]) == today
    if week not in (lesson.get("weekNumber") or []):
        return False
    start = _parse_date(lesson.get("startLessonDate"))
    end = _parse_date(lesson.get("endLessonDate"))
    return (start is None or start <= today) and (end is None or today <= end)


def _format(group: str, today: date, week: int, lessons: list[dict]) -> str:
    lines = [
        f"📅 <b>Расписание группы {escape(group)}</b>",
        f"{WEEKDAYS[today.weekday()]}, {today:%d.%m} · {week}-я неделя",
        "",
    ]
    for ls in lessons:
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
        lines.append(line)
    return "\n".join(lines)


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

    async def today_message(self, group: str) -> str | None:
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                week = await self._get_json(session, f"{API}/current-week")
                data = await self._get_json(session, API, studentGroup=group)
        except GroupNotFound:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise ScheduleUnavailable(repr(e)) from e

        today = datetime.now(self._tz).date()
        day_lessons = (data.get("schedules") or {}).get(WEEKDAYS[today.weekday()], [])
        lessons = sorted(
            (ls for ls in day_lessons if _is_today(ls, today, int(week))),
            key=lambda ls: ls["startLessonTime"],
        )
        if not lessons:
            return None
        return _format(group, today, int(week), lessons)
