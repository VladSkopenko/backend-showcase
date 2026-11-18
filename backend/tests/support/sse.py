import json
from typing import Any


def parse_events(body: str) -> list[tuple[str, Any]]:
    """Turns an event-stream body into (event, data) pairs, the data decoded from JSON."""
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data: list[str] = []
        for line in block.split("\n"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        events.append((event, json.loads("\n".join(data))))
    return events
