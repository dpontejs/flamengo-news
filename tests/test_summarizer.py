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


def responder(group: dict, summary_ids: list[int] | None = None, fail: set[type] = frozenset()):
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema in fail:
            raise LLMError("boom")
        if schema is GroupResponse:
            return group
        if schema is SummaryResponse:
            ids = summary_ids if summary_ids is not None else range(1, MAX_TOPICS + 1)
            return {"summaries": [{"topic_id": i, "summary": f"Resumo {i}."} for i in ids]}
        if schema is IntroResponse:
            return {"headline": "Flamengo vence o Fla-Flu", "intro": "Semana boa. Líder."}
        raise AssertionError(schema)

    return respond


TWO_TOPICS = {
    "topics": [
        {"title": "Vitória no clássico", "article_ids": [1, 2], "importance": 5},
        {"title": "Bastidores", "article_ids": [3], "importance": 2},
    ]
}


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
    assert first.summary == "Resumo 1."
    assert result.topics[1].summary == "Resumo 2."
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


def test_summaries_are_generated_in_a_single_batch_call() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS))

    summarize_edition(ARTICLES, llm)

    assert len(llm.prompts) == 3  # group + batch summary + intro
    summary_prompt = llm.prompts[1]
    assert "[T1] Vitória no clássico" in summary_prompt
    assert "[T2] Bastidores" in summary_prompt


def test_topic_missing_from_batch_keeps_empty_summary() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS, summary_ids=[2, 99]))

    result = summarize_edition(ARTICLES, llm)

    assert [(t.title, t.summary) for t in result.topics] == [
        ("Vitória no clássico", ""),
        ("Bastidores", "Resumo 2."),
    ]


def test_batch_summary_failure_keeps_topics() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS, fail={SummaryResponse}))

    result = summarize_edition(ARTICLES, llm)

    assert [t.title for t in result.topics] == ["Vitória no clássico", "Bastidores"]
    assert all(t.summary == "" for t in result.topics)
    assert result.headline == "Flamengo vence o Fla-Flu"


def test_intro_failure_keeps_topics() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS, fail={IntroResponse}))

    result = summarize_edition(ARTICLES, llm, last_match=LAST_MATCH)

    assert [t.summary for t in result.topics] == ["Resumo 1.", "Resumo 2."]
    assert (result.headline, result.intro) == ("", "")


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


def test_write_analysis_prompt_has_stats_events_and_form() -> None:
    from flanews.models import FormResult, MatchEvent, PlayerRanking, TeamMoment
    from flanews.summarizer.pipeline import AnalysisResponse, write_analysis

    match = LAST_MATCH.model_copy(
        update={
            "statistics": {"Posse de bola": ("43.5%", "56.5%"), "Finalizações": ("17", "12")},
            "events": [
                MatchEvent(minute=65, team="Flamengo", player="Jorge Carrascal", type="goal")
            ],
            "leaders": {"Flamengo": [("Finalizações", "Samuel Lino", "3")]},
        }
    )
    moment = TeamMoment(
        form=[
            FormResult(
                result="V",
                opponent="Fluminense",
                score="1-0",
                competition="Brasileirão",
                date=datetime(2026, 10, 11, tzinfo=TZ),
            )
        ],
        gap="1 ponto à frente do Palmeiras",
        rankings=[PlayerRanking(category="Gols", player="Pedro", position=2, value=16)],
    )
    llm = FakeLLMClient(lambda prompt, schema: {"analysis": " Leitura do jogo. "})

    assert write_analysis(match, moment, llm) == "Leitura do jogo."
    prompt = llm.prompts[0]
    for expected in (
        "Posse de bola: 43.5% x 56.5%",
        "65' Jorge Carrascal",
        "Samuel Lino",
        "V 1-0 Fluminense",
        "1 ponto à frente do Palmeiras",
        "Pedro",
        "não invente",
    ):
        assert expected in prompt or expected in prompt.lower(), expected
    assert AnalysisResponse.model_fields.keys() == {"analysis"}


def test_group_prompt_requires_accented_titles() -> None:
    # flash-lite stripped or replaced accents in 6/15 titles without this rule (0/17 with it).
    llm = FakeLLMClient(responder(TWO_TOPICS))

    summarize_edition(ARTICLES, llm)

    assert "acentuação" in llm.prompts[0]
    assert "nunca remova nem substitua acentos" in llm.prompts[0]


def test_group_prompt_lists_topics_already_published() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS))

    summarize_edition(ARTICLES, llm, published=["Flamengo empata com o Estudiantes"])

    group = llm.prompts[0]
    assert "Já publicado na edição anterior" in group
    assert "- Flamengo empata com o Estudiantes" in group


def test_group_prompt_has_no_published_block_without_history() -> None:
    llm = FakeLLMClient(responder(TWO_TOPICS))

    summarize_edition(ARTICLES, llm)

    assert "Já publicado" not in llm.prompts[0]


def test_pre_game_group_prompt_focuses_on_the_next_match() -> None:
    from flanews.models import NextMatch

    bahia = NextMatch(
        opponent="Bahia",
        competition="Brasileirão",
        date=datetime(2026, 10, 18, 18, 30, tzinfo=TZ),
        is_home=False,
    )
    llm = FakeLLMClient(responder(TWO_TOPICS))

    summarize_edition(ARTICLES, llm, next_match=bahia)

    group = llm.prompts[0]
    assert "edição de pré-jogo de Bahia x Flamengo" in group
    assert "O jogo anterior só entra com fato novo" in group
