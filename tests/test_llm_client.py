import json

import httpx
import pytest
import respx
from fakes import FakeLLMClient
from pydantic import BaseModel
from tenacity import wait_none

from flanews.config import Settings
from flanews.summarizer.client import GeminiClient, LLMError, get_llm_client

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"


class Headline(BaseModel):
    title: str
    importance: int


def gemini_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "finishReason": "STOP",
                }
            ]
        },
    )


def make_client() -> GeminiClient:
    return GeminiClient(api_key="test-key", model="gemini-test", wait=wait_none())


@respx.mock
def test_generate_json_returns_validated_model_and_sends_schema() -> None:
    route = respx.post(GENERATE_URL).mock(
        return_value=gemini_response('{"title": "Flamengo vence", "importance": 5}')
    )

    result = make_client().generate_json("Resuma", Headline)

    assert result == Headline(title="Flamengo vence", importance=5)
    body = json.loads(route.calls.last.request.content)
    assert body["contents"][0]["parts"][0]["text"] == "Resuma"
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert set(config["responseSchema"]["properties"]) == {"title", "importance"}


@respx.mock
def test_generate_json_retries_server_errors_then_succeeds() -> None:
    route = respx.post(GENERATE_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": {"code": 503, "message": "overloaded"}}),
            gemini_response('{"title": "Flamengo vence", "importance": 5}'),
        ]
    )

    result = make_client().generate_json("Resuma", Headline)

    assert result.title == "Flamengo vence"
    assert route.call_count == 2


@respx.mock
def test_generate_json_retries_invalid_json_up_to_three_times() -> None:
    route = respx.post(GENERATE_URL).mock(return_value=gemini_response('{"title": "sem nota"}'))

    with pytest.raises(LLMError):
        make_client().generate_json("Resuma", Headline)
    assert route.call_count == 3


@respx.mock
def test_generate_json_does_not_retry_client_errors() -> None:
    route = respx.post(GENERATE_URL).mock(
        return_value=httpx.Response(400, json={"error": {"code": 400, "message": "bad key"}})
    )

    with pytest.raises(LLMError):
        make_client().generate_json("Resuma", Headline)
    assert route.call_count == 1


def test_get_llm_client_requires_api_key() -> None:
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        get_llm_client(Settings(GEMINI_API_KEY=None))


def test_get_llm_client_uses_configured_model() -> None:
    client = get_llm_client(Settings(GEMINI_API_KEY="k", GEMINI_MODEL="gemini-x"))
    assert isinstance(client, GeminiClient)
    assert client.model == "gemini-x"


def test_fake_llm_client_records_prompts() -> None:
    fake = FakeLLMClient(lambda prompt, schema: {"title": prompt.upper(), "importance": 1})

    result = fake.generate_json("oi", Headline)

    assert result == Headline(title="OI", importance=1)
    assert fake.prompts == ["oi"]
