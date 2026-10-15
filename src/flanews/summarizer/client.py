import logging
from abc import ABC, abstractmethod

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from flanews.config import Settings, get_settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
TIMEOUT_MS = 60_000


class LLMError(Exception):
    """Raised when the LLM cannot produce a valid response."""


class LLMClient(ABC):
    """Interface for LLMs that answer a prompt with JSON matching a pydantic schema."""

    @abstractmethod
    def generate_json[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        """Return the model's answer to `prompt`, validated against `schema`."""


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, errors.ClientError):
        return error.code == 429
    return isinstance(
        error, errors.ServerError | ValidationError | httpx.TransportError | ValueError
    )


class GeminiClient(LLMClient):
    """Gemini client using structured JSON output, with retries and validation."""

    def __init__(
        self,
        api_key: str,
        model: str,
        wait: wait_base | None = None,
    ) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS)
        )
        self._wait = wait or wait_exponential(multiplier=2, max=30)

    def generate_json[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=self._wait,
            retry=retry_if_exception(_is_retryable),
            before_sleep=lambda state: logger.warning(
                "Gemini call failed (attempt %d): %s",
                state.attempt_number,
                state.outcome.exception() if state.outcome else None,
            ),
        )
        try:
            return retrying(self._generate_once, prompt, schema)
        except RetryError as e:
            raise LLMError(
                f"Gemini failed after {MAX_ATTEMPTS} attempts"
            ) from e.last_attempt.exception()
        except Exception as e:
            raise LLMError(f"Gemini request failed: {e}") from e

    def _generate_once[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        if not response.text:
            raise ValueError("empty response from Gemini")
        return schema.model_validate_json(response.text)


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Build the configured LLM client; requires GEMINI_API_KEY."""
    settings = settings or get_settings()
    if not settings.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not configured")
    return GeminiClient(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
