import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Call:
    name: str
    # A string is streamed as it is, so one that is not JSON makes an invalid tool call.
    args: dict[str, Any] | str
    id: str


@dataclass(frozen=True)
class Raise:
    error: Exception


@dataclass(frozen=True)
class Wait:
    seconds: float


@dataclass(frozen=True)
class Act:
    action: Callable[[], None]


Step = Text | Call | Raise | Wait | Act
Script = Sequence[Step]


class ScriptExhaustedError(Exception):
    pass


class FakeChatModel(BaseChatModel):
    """Plays one script per model call: text chunks, tool-call chunks, a failure or a stall."""

    scripts: Sequence[Script]
    received: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[BaseTool] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        self.bound_tools = [tool for tool in tools if isinstance(tool, BaseTool)]
        return cast(Runnable[LanguageModelInput, AIMessage], self)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("The fake model only streams.")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.received.append(list(messages))
        if len(self.received) > len(self.scripts):
            raise ScriptExhaustedError(
                f"the fake model was called {len(self.received)} times "
                f"but has {len(self.scripts)} scripts"
            )
        for index, step in enumerate(self.scripts[len(self.received) - 1]):
            match step:
                case Text(text):
                    yield ChatGenerationChunk(message=AIMessageChunk(content=text))
                case Call(name, args, id):
                    raw = args if isinstance(args, str) else json.dumps(args)
                    chunk = tool_call_chunk(name=name, args=raw, id=id, index=index)
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(content="", tool_call_chunks=[chunk])
                    )
                case Raise(error):
                    raise error
                case Wait(seconds):
                    await asyncio.sleep(seconds)
                case Act(action):
                    action()
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))
