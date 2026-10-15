import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import respx

from flanews.collectors.candidates import (
    BRAZIL_GOOGLE_NEWS_QUERY,
    BRAZIL_LIMIT,
    EXTRA_LIMIT,
    GE_FOOTBALL_RSS_URL,
    GE_SERIE_A_RSS_URL,
    BrazilCollector,
    ExtrasCollector,
)
from flanews.collectors.google_news import google_news_url

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("America/Sao_Paulo")
START = datetime(2026, 10, 8, 8, tzinfo=TZ)
END = datetime(2026, 10, 15, 8, tzinfo=TZ)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@respx.mock
def test_extras_collector_tags_section_and_category() -> None:
    respx.get(google_news_url("basquete")).mock(
        return_value=httpx.Response(200, text=fixture("google_news_basquete.xml"))
    )

    articles = ExtrasCollector({"Basquete": "basquete"}, client=httpx.Client()).collect(START, END)

    # 43 items fall in the window; only the 15 most recent are kept.
    assert len(articles) == EXTRA_LIMIT
    assert all(a.section == "saiba_mais" and a.category == "Basquete" for a in articles)
    assert all(START <= a.published_at <= END for a in articles)
    dates = [a.published_at for a in articles]
    assert dates == sorted(dates, reverse=True)


@respx.mock
def test_extras_collector_survives_failing_extra() -> None:
    respx.get(google_news_url("basquete")).mock(
        return_value=httpx.Response(200, text=fixture("google_news_basquete.xml"))
    )
    respx.get(google_news_url("volei")).mock(return_value=httpx.Response(500))

    articles = ExtrasCollector(
        {"Vôlei": "volei", "Basquete": "basquete"}, client=httpx.Client()
    ).collect(START, END)

    assert articles and {a.category for a in articles} == {"Basquete"}


@respx.mock
def test_brazil_collector_excludes_flamengo_and_strips_html() -> None:
    respx.get(GE_FOOTBALL_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_futebol_rss.xml"))
    )
    respx.get(GE_SERIE_A_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_serie_a_rss.xml"))
    )
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(
        return_value=httpx.Response(200, text=fixture("google_news_brasil.xml"))
    )

    articles = BrazilCollector(client=httpx.Client()).collect(START, END)

    assert 0 < len(articles) <= BRAZIL_LIMIT
    assert all(a.section == "brasil" for a in articles)
    assert {a.source.split(":")[0] for a in articles} <= {"ge", "google_news"}
    assert all(START <= a.published_at <= END for a in articles)
    for a in articles:
        assert "flamengo" not in a.title.lower()
        assert not re.search(r"<[a-zA-Z/][^>]*>", a.summary_hint or "")
    dates = [a.published_at for a in articles]
    assert dates == sorted(dates, reverse=True)


@respx.mock
def test_brazil_collector_error_returns_empty() -> None:
    respx.get(GE_FOOTBALL_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(GE_SERIE_A_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(return_value=httpx.Response(503))
    assert BrazilCollector(client=httpx.Client()).collect(START, END) == []


@respx.mock
def test_brazil_collector_covers_whole_window_with_serie_a_feed() -> None:
    # The general football feed spans ~23h; a Monday edition window is 3 days.
    respx.get(GE_FOOTBALL_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_futebol_rss.xml"))
    )
    respx.get(GE_SERIE_A_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_serie_a_rss.xml"))
    )
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(
        return_value=httpx.Response(200, text=fixture("google_news_brasil.xml"))
    )
    start, end = datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)

    articles = BrazilCollector(client=httpx.Client()).collect(start, end)

    assert articles
    assert len({a.url for a in articles}) == len(articles)


@respx.mock
def test_brazil_collector_keeps_working_when_one_feed_fails() -> None:
    respx.get(GE_FOOTBALL_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(GE_SERIE_A_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_serie_a_rss.xml"))
    )
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(
        return_value=httpx.Response(200, text=fixture("google_news_brasil.xml"))
    )
    start, end = datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)

    assert BrazilCollector(client=httpx.Client()).collect(start, end)


@respx.mock
def test_extras_collector_drops_social_media_posts() -> None:
    respx.get(google_news_url("basquete")).mock(
        return_value=httpx.Response(200, text=fixture("google_news_basquete.xml"))
    )

    # Window ends right after the fixture's Instagram post (11/10 15:51), so it would
    # be among the 15 most recent if it were not filtered out.
    articles = ExtrasCollector({"Basquete": "basquete"}, client=httpx.Client()).collect(
        datetime(2026, 10, 8, tzinfo=TZ), datetime(2026, 10, 11, 16, tzinfo=TZ)
    )

    assert articles
    social = {"instagram", "facebook", "tiktok", "youtube", "x"}
    assert not any(a.source.split(":", 1)[-1].lower() in social for a in articles)


@respx.mock
def test_brazil_collector_keeps_news_that_only_mention_flamengo_in_summary() -> None:
    respx.get(GE_FOOTBALL_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(GE_SERIE_A_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_serie_a_rss.xml"))
    )
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(return_value=httpx.Response(503))
    start, end = datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)

    titles = [a.title for a in BrazilCollector(client=httpx.Client()).collect(start, end)]

    assert any(t.startswith("Palmeiras fez do atropelo no Dérbi") for t in titles)
    assert not any("Flamengo" in t for t in titles)


@respx.mock
def test_brazil_collector_adds_google_news_results() -> None:
    respx.get(GE_FOOTBALL_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(GE_SERIE_A_RSS_URL).mock(return_value=httpx.Response(503))
    respx.get(google_news_url(BRAZIL_GOOGLE_NEWS_QUERY)).mock(
        return_value=httpx.Response(200, text=fixture("google_news_brasil.xml"))
    )

    articles = BrazilCollector(client=httpx.Client()).collect(START, END)

    assert articles
    assert all(a.section == "brasil" and a.source.startswith("google_news") for a in articles)
