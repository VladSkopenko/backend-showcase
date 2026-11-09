class HealthOpenApiTags:
    HEALTH = "Health"

    METADATA = [
        {
            "name": HEALTH,
            "description": (
                "Liveness of the service and its database; the deploy gate probes /health."
            ),
        },
    ]
