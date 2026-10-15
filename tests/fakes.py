from collections.abc import Callable

from pydantic import BaseModel

from flanews.summarizer.client import LLMClient


class FakeLLMClient(LLMClient):
    """LLM client returning canned responses; records every prompt it receives."""

    def __init__(self, responder: Callable[[str, type[BaseModel]], BaseModel | dict]) -> None:
        self.responder = responder
        self.prompts: list[str] = []

    def generate_json[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        self.prompts.append(prompt)
        result = self.responder(prompt, schema)
        return schema.model_validate(result if isinstance(result, dict) else result.model_dump())
