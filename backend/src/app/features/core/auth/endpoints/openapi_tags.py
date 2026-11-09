class AuthOpenApiTags:
    REGISTRATION = "Registration"
    PASSWORD_RESET = "Password reset"
    SESSION = "Session"
    OAUTH = "OAuth sign-in"

    METADATA = [
        {
            "name": REGISTRATION,
            "description": (
                "Create an account and confirm its email with a 6-digit code: register, "
                "then verify-email; resend-code sends a new code."
            ),
        },
        {
            "name": PASSWORD_RESET,
            "description": (
                "Forgotten password: request emails a code, verify-code checks it, confirm sets "
                "the new password and ends every session. No sign-in afterwards."
            ),
        },
        {
            "name": SESSION,
            "description": (
                "Password sign-in and the session in HttpOnly cookies: login, refresh, logout, "
                "and me for the current user."
            ),
        },
        {
            "name": OAUTH,
            "description": (
                "Sign in with an external provider (Google). Browser navigations through the "
                "frontend proxy that answer with redirects and set the session cookies."
            ),
        },
    ]
