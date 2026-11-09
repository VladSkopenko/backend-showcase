from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Response, status
from fastapi.responses import JSONResponse

from app.common.error_responses import domain_error_response
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

RefreshTokenCookie = Annotated[str | None, Cookie(alias=SessionCookies.REFRESH_NAME)]

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    response_model_exclude_none=True,
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


@router.post("/verify-email", response_model=VerifyEmailResponse)
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


@router.post("/password-reset/verify-code", status_code=status.HTTP_204_NO_CONTENT)
async def verify_password_reset_code(
    body: PasswordResetCodeRequest, password_reset: PasswordResetServiceDep
) -> Response:
    error = await password_reset.verify_code(email=body.email, code=body.code)
    if error is not None:
        return domain_error_response(error, ERROR_STATUSES)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest, password_reset: PasswordResetServiceDep
) -> Response:
    error = await password_reset.confirm(email=body.email, code=body.code, password=body.password)
    if error is not None:
        return domain_error_response(error, ERROR_STATUSES)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login", response_model=UserResponse)
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


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def log_out(
    sessions: SessionServiceDep,
    cookies: SessionCookiesDep,
    refresh_token: RefreshTokenCookie = None,
) -> Response:
    await sessions.end(refresh_token=refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    cookies.clear(response=response)
    return response


@router.get("/me", response_model=UserResponse)
async def read_current_user(user: CurrentUserDep) -> UserResponse:
    return user
