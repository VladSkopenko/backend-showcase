import asyncio

import anyio.to_thread
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


class PasswordHasher:
    def __init__(self) -> None:
        self._argon2 = PasswordHash((Argon2Hasher(memory_cost=19456, time_cost=2),))
        self._slots = asyncio.Semaphore(1)

    async def hash(self, *, password: str) -> str:
        async with self._slots:
            return await anyio.to_thread.run_sync(self._argon2.hash, password)

    async def verify(self, *, password: str, password_hash: str) -> bool:
        async with self._slots:
            return await anyio.to_thread.run_sync(self._argon2.verify, password, password_hash)
