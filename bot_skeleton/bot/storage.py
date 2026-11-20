import aiosqlite


class SqliteChatRepository:
    def __init__(self, path: str) -> None:
        self._path = path

    async def init(self) -> None:
        """Создаёт таблицу, если её ещё нет."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS chats ("
                "chat_id INTEGER PRIMARY KEY, "
                "group_number TEXT NOT NULL)"
            )
            await db.commit()

    async def set_group(self, chat_id: int, group: str) -> None:
        """Новая беседа и смена группы — одним запросом."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO chats (chat_id, group_number) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET group_number = excluded.group_number",
                (chat_id, group),
            )
            await db.commit()

    async def get_group(self, chat_id: int) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                "SELECT group_number FROM chats WHERE chat_id = ?", (chat_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    async def remove_chat(self, chat_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def all_subscriptions(self) -> dict[str, list[int]]:
        """Возвращает {группа: [chat_id, ...]}, чтобы C++ вызывался один раз на группу."""
        result: dict[str, list[int]] = {}
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("SELECT group_number, chat_id FROM chats") as cursor:
                async for group, chat_id in cursor:
                    result.setdefault(group, []).append(chat_id)
        return result