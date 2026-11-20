"""Провайдер расписания: запускает C++-программу и оформляет её вывод для Telegram."""
import asyncio
import subprocess
from datetime import date, timedelta
from html import escape
from zoneinfo import ZoneInfo

from bot.interfaces import GroupNotFound, ScheduleUnavailable

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
GROUP_NOT_FOUND_CODE = 2  # код выхода C++-программы: группа не найдена
FIELDS = 7  # полей в строке вывода: начало, конец, предмет, тип, аудитории, подгруппа, преподаватель


def _parse_output(stdout: str) -> list[list[str]]:
    """Разбирает вывод C++: одна пара — одна строка, поля через табуляцию."""
    lessons = []
    for line in stdout.split("\n"):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 3:  # нет даже времени и предмета
            raise ScheduleUnavailable(f"неожиданная строка вывода: {line!r}")
        fields += [""] * (FIELDS - len(fields))
        lessons.append([f.strip() for f in fields[:FIELDS]])
    return sorted(lessons, key=lambda f: f[0])


def _format_lesson(fields: list[str]) -> str:
    start, end, subject, lesson_type, auditories, subgroup, teacher = fields
    line = f"🕘 {escape(start)}–{escape(end)} · <b>{escape(subject)}</b>"
    if lesson_type:
        line += f" ({escape(lesson_type)})"
    if auditories:
        line += f" · {escape(auditories)}"
    if subgroup not in ("", "0"):  # 0 — занятие для всей группы
        line += f" · подгр. {escape(subgroup)}"
    if teacher:
        line += f"\n      👤 {escape(teacher)}"
    return line


class CppScheduleProvider:
    def __init__(self, binary_path: str, tz: ZoneInfo, timeout: float = 15) -> None:
        self._binary = binary_path
        self._tz = tz  # дату всегда передаёт бот, часовой пояс здесь пока не нужен
        self._timeout = timeout

    async def _lessons(self, group: str, day: date) -> list[list[str]]:
        """Запускает C++ для одной даты в отдельном потоке, чтобы не блокировать бота."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._binary, group, day.isoformat()],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise ScheduleUnavailable(f"C++-модуль не ответил за {self._timeout} с") from e
        except OSError as e:
            raise ScheduleUnavailable(f"не удалось запустить {self._binary}: {e!r}") from e

        if result.returncode == GROUP_NOT_FOUND_CODE:
            raise GroupNotFound(group)
        if result.returncode != 0:
            raise ScheduleUnavailable(f"код выхода {result.returncode}: {result.stderr.strip()}")
        return _parse_output(result.stdout)

    async def day_message(self, group: str, day: date) -> str | None:
        lessons = await self._lessons(group, day)
        if not lessons:
            return None
        return "\n".join([
            f"📅 <b>Расписание группы {escape(group)}</b>",
            f"{WEEKDAYS[day.weekday()]}, {day:%d.%m}",
            "",
            *map(_format_lesson, lessons),
        ])

    async def week_message(self, group: str, start: date) -> str | None:
        # 7 дней начиная с start, воскресенья пропускаем; неделю для каждой даты считает C++
        days = [d for d in (start + timedelta(days=i) for i in range(7)) if d.weekday() != 6]
        results = await asyncio.gather(*(self._lessons(group, d) for d in days))
        blocks = [
            f"<b>{WEEKDAYS[d.weekday()]}, {d:%d.%m}</b>\n" + "\n".join(map(_format_lesson, lessons))
            for d, lessons in zip(days, results)
            if lessons
        ]
        if not blocks:
            return None
        end = start + timedelta(days=6)
        header = f"🗓 <b>Группа {escape(group)} · 7 дней</b>\n{start:%d.%m}–{end:%d.%m}"
        return "\n\n".join([header, *blocks])