from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Response, status
from fastapi.responses import JSONResponse

from app.common.error_responses import domain_error_response, error_responses
from app.features.core.auth.dto import RegistrationCommand
from app.features.core.auth.endpoints.cookies import SessionCookies
from app.features.core.auth.endpoints.dependencies import (
    CurrentUserDep,
    EmailVerificationServiceDep,
    LoginServiceDep,
    PasswordResetServiceDep,
    RegistrationServiceDep,
    SessionCookiesDep,
    SessionServiceDep,
    VerificationEmailServiceDep,
)
from app.features.core.auth.endpoints.errors import ERROR_STATUSES
from app.features.core.auth.endpoints.openapi_tags import AuthOpenApiTags
from app.features.core.auth.schemas import (
    LoginRequest,
    PasswordResetCodeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    RegisterResponse,
    ResendCodeRequest,
    ResendCodeResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.features.core.auth.services.exceptions import (
    AccountLockedError,
    AlreadyVerifiedError,
    CodeExpiredError,
    CodeInvalidError,
    EmailNotVerifiedError,
    EmailTakenError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    ResendTooSoonError,
    SessionInvalidError,
    UserNotFoundError,
)

RefreshTokenCookie = Annotated[str | None, Cookie(alias=SessionCookies.REFRESH_NAME)]

router = APIRouter(prefix="/auth")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    response_model_exclude_none=True,
    tags=[AuthOpenApiTags.REGISTRATION],
    responses=error_responses(
        EmailTakenError,
        ResendTooSoonError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Creates an unverified account and emails a 6-digit code that expires. Registering "
        "an unverified email again replaces that account. `debug_code` is returned only in "
        "local."
    ),
)
async def register_user(
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    registration: RegistrationServiceDep,
    verification_email: VerificationEmailServiceDep,
) -> RegisterResponse:
    command = RegistrationCommand(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
    )
    issued = await registration.register(command=command)
    background_tasks.add_task(verification_email.send, issued=issued)
    return RegisterResponse(
        id=issued.user.id, email=issued.user.email, debug_code=issued.debug_code
    )


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    tags=[AuthOpenApiTags.REGISTRATION],
    responses=error_responses(
        CodeInvalidError,
        CodeExpiredError,
        UserNotFoundError,
        AlreadyVerifiedError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Confirms the email with the code and signs the user in: sets the session cookies. "
        "Wrong codes count toward a limit of attempts."
    ),
)
async def verify_user_email(
    body: VerifyEmailRequest,
    email_verification: EmailVerificationServiceDep,
    cookies: SessionCookiesDep,
) -> JSONResponse:
    outcome = await email_verification.verify(email=body.email, code=body.code)
    if outcome.error is not None:
        return domain_error_response(outcome.error, ERROR_STATUSES)
    assert outcome.session is not None
    response = JSONResponse(
        VerifyEmailResponse.model_validate(outcome.user).model_dump(mode="json")
    )
    cookies.set(response=response, session=outcome.session)
    return response


@router.post(
    "/resend-code",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResendCodeResponse,
    response_model_exclude_none=True,
    tags=[AuthOpenApiTags.REGISTRATION],
    responses=error_responses(
        UserNotFoundError,
        AlreadyVerifiedError,
        ResendTooSoonError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Emails a new verification code to an unverified account; codes are rate-limited "
        "(cooldown, hourly cap)."
    ),
)
async def resend_verification_code(
    body: ResendCodeRequest,
    background_tasks: BackgroundTasks,
    email_verification: EmailVerificationServiceDep,
    verification_email: VerificationEmailServiceDep,
) -> ResendCodeResponse:
    issued = await email_verification.resend(email=body.email)
    background_tasks.add_task(verification_email.send, issued=issued)
    return ResendCodeResponse(debug_code=issued.debug_code)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResendCodeResponse,
    response_model_exclude_none=True,
    tags=[AuthOpenApiTags.PASSWORD_RESET],
    responses=error_responses(
        UserNotFoundError,
        ResendTooSoonError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Emails a password reset code that expires; calling it again resends. Codes are "
        "rate-limited (cooldown, hourly and daily caps)."
    ),
)
async def request_password_reset(
    body: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    password_reset: PasswordResetServiceDep,
    verification_email: VerificationEmailServiceDep,
) -> ResendCodeResponse:
    issued = await password_reset.request(email=body.email)
    background_tasks.add_task(verification_email.send, issued=issued)
    return ResendCodeResponse(debug_code=issued.debug_code)


@router.post(
    "/password-reset/verify-code",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=[AuthOpenApiTags.PASSWORD_RESET],
    responses=error_responses(
        CodeInvalidError,
        CodeExpiredError,
        UserNotFoundError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Checks the reset code without using it up (the Confirm step). Wrong codes count "
        "toward a limit of attempts."
    ),
)
async def verify_password_reset_code(
    body: PasswordResetCodeRequest, password_reset: PasswordResetServiceDep
) -> Response:
    error = await password_reset.verify_code(email=body.email, code=body.code)
    if error is not None:
        return domain_error_response(error, ERROR_STATUSES)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=[AuthOpenApiTags.PASSWORD_RESET],
    responses=error_responses(
        CodeInvalidError,
        CodeExpiredError,
        UserNotFoundError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Checks and uses up the code, sets the new password, verifies the email if it was "
        "not, clears the login lockout and ends every session. Does not sign in."
    ),
)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest, password_reset: PasswordResetServiceDep
) -> Response:
    error = await password_reset.confirm(email=body.email, code=body.code, password=body.password)
    if error is not None:
        return domain_error_response(error, ERROR_STATUSES)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/login",
    response_model=UserResponse,
    tags=[AuthOpenApiTags.SESSION],
    responses=error_responses(
        InvalidCredentialsError,
        EmailNotVerifiedError,
        AccountLockedError,
        statuses=ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Signs in with email and password and sets the session cookies. Repeated wrong "
        "passwords lock login for a while (423)."
    ),
)
async def log_in(
    body: LoginRequest, login: LoginServiceDep, cookies: SessionCookiesDep
) -> JSONResponse:
    outcome = await login.log_in(email=body.email, password=body.password)
    if outcome.error is not None:
        return domain_error_response(outcome.error, ERROR_STATUSES)
    assert outcome.session is not None
    response = JSONResponse(UserResponse.model_validate(outcome.user).model_dump(mode="json"))
    cookies.set(response=response, session=outcome.session)
    return response


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=[AuthOpenApiTags.SESSION],
    responses=error_responses(SessionInvalidError, statuses=ERROR_STATUSES, takes_input=True),
    description=(
        "Rotates the refresh cookie and sets a new pair. Presenting an already rotated token "
        "ends every session."
    ),
)
async def refresh_session(
    sessions: SessionServiceDep,
    cookies: SessionCookiesDep,
    refresh_token: RefreshTokenCookie = None,
) -> Response:
    outcome = await sessions.refresh(refresh_token=refresh_token)
    if outcome.error is not None:
        response: Response = domain_error_response(outcome.error, ERROR_STATUSES)
        cookies.clear(response=response)
        return response
    assert outcome.session is not None
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    cookies.set(response=response, session=outcome.session)
    return response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=[AuthOpenApiTags.SESSION],
    responses=error_responses(takes_input=True),
    description="Ends the session of the refresh cookie and clears both cookies.",
)
async def log_out(
    sessions: SessionServiceDep,
    cookies: SessionCookiesDep,
    refresh_token: RefreshTokenCookie = None,
) -> Response:
    await sessions.end(refresh_token=refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    cookies.clear(response=response)
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    tags=[AuthOpenApiTags.SESSION],
    responses=error_responses(NotAuthenticatedError, statuses=ERROR_STATUSES, takes_input=True),
    description="Returns the user signed in with the access cookie.",
)
async def read_current_user(user: CurrentUserDep) -> UserResponse:
    return user
