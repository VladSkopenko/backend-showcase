from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseProbeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
