class AssistantOpenApiTags:
    ASSISTANT = "Assistant"

    METADATA = [
        {
            "name": ASSISTANT,
            "description": (
                "The AI assistant on the website: a signed-in user with a verified email keeps "
                "chat sessions with their messages. Sessions without activity for a while are "
                "deleted. Unavailable when the model provider is not configured."
            ),
        },
    ]
