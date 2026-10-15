from datetime import datetime
from zoneinfo import ZoneInfo

from fakes import FakeLLMClient
from pydantic import BaseModel

from flanews.models import Article, Brief
from flanews.summarizer.pipeline import (
    BRAZIL_PICKS,
    LEARN_MORE_PICKS,
    GroupResponse,
    IntroResponse,
    SummaryResponse,
    summarize_edition,
)

TZ = ZoneInfo("America/Sao_Paulo")


def article(i: int, section: str = "flamengo", category: str | None = None) -> Article:
    return Article(
        url=f"https://x.com/{section}/{i}",
        title=f"{section} notícia {i}",
        source="ge",
        published_at=datetime(2026, 10, 11, tzinfo=TZ),
        summary_hint=f"hint {section} {i}",
        section=section,
        category=category,
    )


MAIN = [article(1)]
EXTRAS = [article(i, "saiba_mais", "Basquete") for i in range(1, 6)]
BRAZIL = [article(i, "brasil") for i in range(1, 9)]


def responder(learn_more_ids, brazil_ids, briefs=None):
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is GroupResponse:
            return {
                "topics": [{"title": "Fla", "article_ids": [1], "importance": 5}],
                "learn_more_ids": learn_more_ids,
                "brazil_ids": brazil_ids,
            }
        if schema is SummaryResponse:
            return {
                "summaries": [{"topic_id": 1, "summary": "Resumo."}],
                "briefs": briefs if briefs is not None else [],
            }
        if schema is IntroResponse:
            return {"headline": "H", "intro": "I"}
        raise AssertionError(schema)

    return respond


def run(llm, extracted: list | None = None):
    def extract(articles: list[Article]) -> list[Article]:
        if extracted is not None:
            extracted.extend(articles)
        return [a.model_copy(update={"content": f"texto de {a.title}"}) for a in articles]

    return summarize_edition(MAIN, llm, learn_more=EXTRAS, brazil=BRAZIL, extract=extract)


def test_picks_valid_ids_in_order_and_caps_each_section() -> None:
    llm = FakeLLMClient(responder([5, 99, 0, 5, 2, 1, 3], [8, 1, 2, 3, 4, 5, 6, -1]))

    result = run(llm)

    assert [b.url for b in result.learn_more] == [
        "https://x.com/saiba_mais/5",
        "https://x.com/saiba_mais/2",
        "https://x.com/saiba_mais/1",
    ][:LEARN_MORE_PICKS]
    assert len(result.around_brazil) == BRAZIL_PICKS
    assert result.around_brazil[0].url == "https://x.com/brasil/8"
    assert result.learn_more[0].category == "Basquete"


def test_only_picked_candidates_are_extracted() -> None:
    extracted: list[Article] = []
    llm = FakeLLMClient(responder([2], [3]))

    run(llm, extracted)

    assert [a.url for a in extracted] == ["https://x.com/saiba_mais/2", "https://x.com/brasil/3"]
    summary_prompt = llm.prompts[1]
    assert "texto de saiba_mais notícia 2" in summary_prompt
    assert "[S1] saiba_mais notícia 2" in summary_prompt
    assert "[B1] brasil notícia 3" in summary_prompt


def test_briefs_get_one_sentence_and_missing_ones_stay_empty() -> None:
    llm = FakeLLMClient(
        responder(
            [2, 4],
            [3],
            briefs=[{"item_id": "S2", "summary": " Frase S2. "}, {"item_id": "X9", "summary": "?"}],
        )
    )

    result = run(llm)

    assert [b.summary for b in result.learn_more] == ["", "Frase S2."]
    assert result.around_brazil == [
        Brief(
            title="brasil notícia 3",
            summary="",
            url="https://x.com/brasil/3",
            source="ge",
            category=None,
        )
    ]


def test_selection_keeps_llm_budget_at_three_calls() -> None:
    llm = FakeLLMClient(responder([1], [1]))

    run(llm)

    assert len(llm.prompts) == 3  # group + batch summary + intro


def test_group_prompt_lists_candidates_with_category() -> None:
    llm = FakeLLMClient(responder([], []))

    run(llm)

    group_prompt = llm.prompts[0]
    assert "[S1] saiba_mais notícia 1 (Basquete" in group_prompt
    assert "[B8] brasil notícia 8" in group_prompt
    assert "nenhuma" in group_prompt.lower()


def test_no_picks_means_empty_sections() -> None:
    llm = FakeLLMClient(responder([], []))

    result = run(llm)

    assert result.learn_more == [] and result.around_brazil == []


def test_candidates_alone_still_produce_sections() -> None:
    llm = FakeLLMClient(responder([1], [], briefs=[{"item_id": "S1", "summary": "Frase."}]))

    def respond(prompt, schema):
        data = llm.responder(prompt, schema)
        if schema is GroupResponse:
            data["topics"] = []
        return data

    only = FakeLLMClient(respond)
    result = summarize_edition([], only, learn_more=EXTRAS, brazil=[], extract=lambda a: a)

    assert result.topics == []
    assert [b.summary for b in result.learn_more] == ["Frase."]


def test_group_prompt_separates_numbering_and_avoids_repeated_subjects() -> None:
    # Real run: the model put candidate ids in topics and picked the same story twice.
    llm = FakeLLMClient(responder([], []))

    run(llm)

    group_prompt = llm.prompts[0]
    assert "nunca os códigos [S…] ou [B…]" in group_prompt
    learn_more_part = group_prompt[
        group_prompt.index("Saiba mais") : group_prompt.index("Brasil afora")
    ]
    assert "sem repetir o mesmo assunto" in learn_more_part


def test_briefs_drop_outlet_suffix_from_google_news_titles() -> None:
    gn = article(1, "saiba_mais", "Basquete").model_copy(
        update={
            "title": "Flamengo é campeão do Torneio de Abertura - Liga Nacional de Basquete",
            "source": "google_news:Liga Nacional de Basquete",
        }
    )
    llm = FakeLLMClient(responder([1], []))

    result = summarize_edition(MAIN, llm, learn_more=[gn], brazil=[], extract=lambda a: a)

    assert result.learn_more[0].title == "Flamengo é campeão do Torneio de Abertura"
