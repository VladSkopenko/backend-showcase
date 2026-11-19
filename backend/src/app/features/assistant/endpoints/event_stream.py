from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse
from pydantic_core import to_json

from app.features.assistant.dto import AssistantEvent


class EventStreamResponse(StreamingResponse):
    """Server-Sent Events; the headers keep proxies from buffering the stream.

    The media type is set per instance, not on the class: FastAPI would otherwise document every
    response of the route with it, and the refusals before the stream are plain JSON.
    """

    MEDIA_TYPE = "text/event-stream"
    HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    def __init__(self, events: AsyncIterator[AssistantEvent]) -> None:
        super().__init__(self._encode(events), headers=self.HEADERS, media_type=self.MEDIA_TYPE)

    @staticmethod
    async def _encode(events: AsyncIterator[AssistantEvent]) -> AsyncIterator[str]:
        async for event in events:
            yield f"event: {event.name.value}\ndata: {to_json(event.data).decode()}\n\n"
