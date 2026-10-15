from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeLLMClient
from pydantic import BaseModel

from flanews.models import Article, MatchStats, Topic
from flanews.summarizer.client import LLMError
from flanews.summarizer.pipeline import (
    MAX_TOPICS,
    GroupResponse,
    IntroResponse,
    SummaryResponse,
    summarize_edition,
)

TZ = ZoneInfo("America/Sao_Paulo")


def make_article(i: int, content: str | None = None) -> Article:
    return Article(
        url=f"https://ge.globo.com/{i}",
        title=f"Notícia {i} do Flamengo",
        source="ge",
        published_at=datetime(2026, 10, 11, 12, tzinfo=TZ),
        summary_hint=f"hint {i}",
        content=content,
    )


ARTICLES = [make_article(1, "Texto completo 1"), make_article(2), make_article(3)]
LAST_MATCH = MatchStats(
    fixture_id=1,
    competition="Brasileirão",
    date=datetime(2026, 10, 11, 18, tzinfo=TZ),
    home="Flamengo",
    away="Fluminense",
    home_goals=1,
    away_goals=0,
)


def responder(group: dict, fail_summary_for: str | None = None):
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is GroupResponse:
            return group
        if schema is SummaryResponse:
            if fail_summary_for and fail_summary_for in prompt:
                raise LLMError("boom")
            return {"summary": "Resumo do tópico."}
        if schema is IntroResponse:
            return {"headline": "Flamengo vence o Fla-Flu", "intro": "Semana boa. Líder."}
        raise AssertionError(schema)

    return respond


def test_summarize_edition_builds_topics_ordered_by_importance() -> None:
    llm = FakeLLMClient(
        responder(
            {
                "topics": [
                    {"title": "Bastidores", "article_ids": [3], "importance": 2},
                    {"title": "Vitória no clássico", "article_ids": [1, 2], "importance": 5},
                ]
            }
        )
    )

    result = summarize_edition(ARTICLES, llm, last_match=LAST_MATCH)

    assert [t.title for t in result.topics] == ["Vitória no clássico", "Bastidores"]
    first = result.topics[0]
    assert isinstance(first, Topic)
    assert first.summary == "Resumo do tópico."
    assert first.importance == 5
    assert [a.url for a in first.articles] == ["https://ge.globo.com/1", "https://ge.globo.com/2"]
    assert result.headline == "Flamengo vence o Fla-Flu"
    assert result.intro == "Semana boa. Líder."


def test_summarize_edition_ignores_invalid_ids_and_empty_topics() -> None:
    llm = FakeLLMClient(
        responder(
            {
                "topics": [
                    {"title": "Válido", "article_ids": [1, 99, 0, -1, 1], "importance": 3},
                    {"title": "Só ids inválidos", "article_ids": [42], "importance": 5},
                ]
            }
        )
    )

    result = summarize_edition(ARTICLES, llm)

    assert [t.title for t in result.topics] == ["Válido"]
    assert [a.url for a in result.topics[0].articles] == ["https://ge.globo.com/1"]


def test_summarize_edition_limits_topics_and_clamps_importance() -> None:
    topics = [
        {"title": f"Tópico {i}", "article_ids": [1], "importance": 9 if i == 0 else 1}
        for i in range(MAX_TOPICS + 3)
    ]
    llm = FakeLLMClient(responder({"topics": topics}))

    result = summarize_edition(ARTICLES, llm)

    assert len(result.topics) == MAX_TOPICS
    assert result.topics[0].importance == 5


def test_summarize_edition_skips_topic_whose_summary_fails() -> None:
    llm = FakeLLMClient(
        responder(
            {
                "topics": [
                    {"title": "Quebra", "article_ids": [1], "importance": 5},
                    {"title": "Funciona", "article_ids": [2], "importance": 4},
                ]
            },
            fail_summary_for="Quebra",
        )
    )

    result = summarize_edition(ARTICLES, llm)

    assert [t.title for t in result.topics] == ["Funciona"]


def test_prompts_include_article_data_in_portuguese() -> None:
    llm = FakeLLMClient(
        responder({"topics": [{"title": "Vitória", "article_ids": [1], "importance": 5}]})
    )

    summarize_edition(ARTICLES, llm, last_match=LAST_MATCH)

    group_prompt, summary_prompt, intro_prompt = llm.prompts
    assert "[2] Notícia 2 do Flamengo" in group_prompt
    assert "hint 2" in group_prompt
    assert "Texto completo 1" in summary_prompt
    assert "não invente" in summary_prompt.lower()
    assert "Vitória" in intro_prompt
    assert "Flamengo 1 x 0 Fluminense" in intro_prompt


def test_summarize_edition_without_articles_or_match_makes_no_calls() -> None:
    llm = FakeLLMClient(responder({"topics": []}))

    result = summarize_edition([], llm)

    assert result.topics == []
    assert result.headline == ""
    assert llm.prompts == []


def test_summarize_edition_with_only_match_writes_intro() -> None:
    llm = FakeLLMClient(responder({"topics": []}))

    result = summarize_edition([], llm, last_match=LAST_MATCH)

    assert result.topics == []
    assert result.headline == "Flamengo vence o Fla-Flu"
    assert len(llm.prompts) == 1


def test_group_failure_propagates() -> None:
    def broken(prompt: str, schema: type[BaseModel]) -> dict:
        raise LLMError("down")

    with pytest.raises(LLMError):
        summarize_edition(ARTICLES, FakeLLMClient(broken))
