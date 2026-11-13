class NotificationsOpenApiTags:
    NOTIFICATIONS = "Notifications"

    METADATA = [
        {
            "name": NOTIFICATIONS,
            "description": (
                "In-app notifications of the signed-in user: the restaurant's decisions on "
                "large-party booking requests the user takes part in. List them, newest first, "
                "and mark them read. Each decision also emails them, except addresses on skipped "
                "domains; without a configured mail server the email is only logged. Needs "
                "sign-in. Times are in the restaurant's time zone."
            ),
        },
    ]
