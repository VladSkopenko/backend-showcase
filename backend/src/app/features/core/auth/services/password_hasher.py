import anyio.to_thread
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


class PasswordHasher:
    def __init__(self) -> None:
        self._argon2 = PasswordHash((Argon2Hasher(),))

    # Argon2 is deliberately slow, so it runs in a worker thread to keep the event loop free.
    async def hash(self, *, password: str) -> str:
        return await anyio.to_thread.run_sync(self._argon2.hash, password)

    async def verify(self, *, password: str, password_hash: str) -> bool:
        return await anyio.to_thread.run_sync(self._argon2.verify, password, password_hash)
