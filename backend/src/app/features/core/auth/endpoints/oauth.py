from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse

from app.features.core.auth.endpoints.dependencies import (
    OAuthClientsDep,
    OAuthProviderDep,
    OAuthRedirectsDep,
    OAuthSignInServiceDep,
    SessionCookiesDep,
)
from app.features.core.auth.endpoints.oauth_redirects import OAuthRedirects
from app.features.core.auth.endpoints.openapi_tags import AuthOpenApiTags
from app.infrastructure.oauth import OAuthExchangeError

router = APIRouter(prefix="/auth", tags=[AuthOpenApiTags.OAUTH])


@router.get(
    "/{provider_slug}/login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    description=(
        "Open it as a browser navigation, never with fetch: redirects to the provider's "
        "consent screen and sets the oauth_state cookie. Failures redirect to the frontend "
        "with auth_error."
    ),
)
async def start_oauth_sign_in(
    request: Request,
    provider: OAuthProviderDep,
    oauth: OAuthSignInServiceDep,
    clients: OAuthClientsDep,
    redirects: OAuthRedirectsDep,
) -> Response:
    error = oauth.start(provider=provider)
    if error is None:
        callback_path = request.app.url_path_for(
            OAuthRedirects.CALLBACK_ROUTE, provider_slug=provider.slug
        )
        try:
            return await clients.authorize_redirect(
                request=request,
                provider_slug=provider.slug,
                redirect_uri=redirects.callback(path=callback_path),
            )
        except OAuthExchangeError as failure:
            error = oauth.failure_error(failure=failure)
    return RedirectResponse(redirects.error(code=error.code), status_code=status.HTTP_302_FOUND)


@router.get(
    "/{provider_slug}/callback",
    name=OAuthRedirects.CALLBACK_ROUTE,
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    description=(
        "The provider sends the browser here; never call it with fetch. Signs the user in "
        "with the session cookies and redirects to the frontend; failures redirect with "
        "auth_error."
    ),
)
async def complete_oauth_sign_in(
    request: Request,
    provider: OAuthProviderDep,
    oauth: OAuthSignInServiceDep,
    clients: OAuthClientsDep,
    redirects: OAuthRedirectsDep,
    cookies: SessionCookiesDep,
) -> Response:
    try:
        claims = await clients.fetch_claims(request=request, provider_slug=provider.slug)
    except OAuthExchangeError as failure:
        outcome = await oauth.complete(provider=provider, failure=failure)
    else:
        outcome = await oauth.complete(provider=provider, claims=claims)
    if outcome.error is not None:
        return RedirectResponse(
            redirects.error(code=outcome.error.code), status_code=status.HTTP_302_FOUND
        )
    assert outcome.session is not None
    response = RedirectResponse(redirects.success(), status_code=status.HTTP_302_FOUND)
    cookies.set(response=response, session=outcome.session)
    return response
