from fastapi import APIRouter, BackgroundTasks, status
from fastapi.responses import JSONResponse

from app.common.error_responses import domain_error_response
from app.features.core.auth.dto import RegistrationCommand
from app.features.core.auth.endpoints.dependencies import (
    EmailVerificationServiceDep,
    RegistrationServiceDep,
    VerificationEmailServiceDep,
)
from app.features.core.auth.endpoints.errors import ERROR_STATUSES
from app.features.core.auth.schemas import (
    RegisterRequest,
    RegisterResponse,
    ResendCodeRequest,
    ResendCodeResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)

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
    body: VerifyEmailRequest, email_verification: EmailVerificationServiceDep
) -> VerifyEmailResponse | JSONResponse:
    outcome = await email_verification.verify(email=body.email, code=body.code)
    if outcome.error is not None:
        return domain_error_response(outcome.error, ERROR_STATUSES)
    return VerifyEmailResponse.model_validate(outcome.user)


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
