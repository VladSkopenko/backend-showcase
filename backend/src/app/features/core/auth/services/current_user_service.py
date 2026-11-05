from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.auth.services.access_token_codec import AccessTokenCodec
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class CurrentUserService:
    def __init__(self, session: AsyncSession, access_token_codec: AccessTokenCodec) -> None:
        self._user_repository = UserRepository(session)
        self._access_token_codec = access_token_codec

    async def get(self, *, access_token: str | None) -> User:
        if access_token is None:
            raise NotAuthenticatedError()
        user_id = self._access_token_codec.decode(token=access_token)
        user = await self._user_repository.get_by_id(user_id=user_id)
        if user is None:
            raise NotAuthenticatedError()
        return user
