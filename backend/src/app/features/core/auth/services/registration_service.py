from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.auth.dto import IssuedCode, RegistrationCommand
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.services.exceptions import EmailTakenError
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.users.models import User
from app.features.core.users.repositories import UserRepository


class RegistrationService:
    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        code_service: VerificationCodeService,
    ) -> None:
        self._user_repository = UserRepository(session)
        self._password_hasher = password_hasher
        self._code_service = code_service

    async def register(self, *, command: RegistrationCommand) -> IssuedCode:
        # The row lock serialises a re-registration with concurrent verify and resend calls.
        existing = await self._user_repository.get_by_email(email=command.email, for_update=True)
        if existing is None:
            return await self._register_new_user(command=command)
        if existing.email_verified_at is not None:
            raise EmailTakenError()
        return await self._replace_unverified_user(user=existing, command=command)

    async def _register_new_user(self, *, command: RegistrationCommand) -> IssuedCode:
        user = User(
            first_name=command.first_name,
            last_name=command.last_name,
            email=command.email,
            password_hash=await self._password_hasher.hash(password=command.password),
        )
        try:
            await self._user_repository.add(user=user)
        except IntegrityError as exc:
            # A parallel registration inserted the same email after the lookup above.
            if "uq_users_email" in str(exc.orig):
                raise EmailTakenError() from exc
            raise
        return await self._code_service.issue(
            user=user, purpose=VerificationPurpose.EMAIL_VERIFICATION
        )

    async def _replace_unverified_user(
        self, *, user: User, command: RegistrationCommand
    ) -> IssuedCode:
        # Issued first, so a refused code leaves the user untouched.
        issued = await self._code_service.issue(
            user=user, purpose=VerificationPurpose.EMAIL_VERIFICATION
        )
        user.first_name = command.first_name
        user.last_name = command.last_name
        user.password_hash = await self._password_hasher.hash(password=command.password)
        return issued
