import enum


class AssistantEventName(enum.Enum):
    THINKING = "thinking"
    CHUNK = "chunk"
    ACTION = "action"
    DONE = "done"
    ERROR = "error"
