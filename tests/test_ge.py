from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flanews.collectors.base import get_collectors
from flanews.collectors.ge import GE_FLAMENGO_URL, GECollector

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ge_flamengo.html"


@pytest.fixture
def ge_html_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_ge_collector_parse_html(ge_html_fixture: str) -> None:
    collector = GECollector()
    tz = ZoneInfo("America/Sao_Paulo")

    start = datetime(2026, 10, 10, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 23, 59, 59, tzinfo=tz)

    articles = collector.parse_html(ge_html_fixture, start, end)

    # Acceptance: extracts at least 5 articles with absolute URL
    assert len(articles) >= 5
    for article in articles:
        assert article.source == "ge"
        assert article.title
        assert article.url.startswith("https://ge.globo.com/")
        assert article.published_at.tzinfo is not None


@respx.mock
def test_ge_collector_network_success(ge_html_fixture: str) -> None:
    respx.get(GE_FLAMENGO_URL).mock(return_value=httpx.Response(200, text=ge_html_fixture))

    collector = GECollector()
    tz = ZoneInfo("America/Sao_Paulo")

    start = datetime(2026, 10, 10, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 23, 59, 59, tzinfo=tz)

    articles = collector.collect(start, end)
    assert len(articles) >= 5


@respx.mock
def test_ge_collector_network_error() -> None:
    respx.get(GE_FLAMENGO_URL).mock(return_value=httpx.Response(500))

    collector = GECollector()
    tz = ZoneInfo("America/Sao_Paulo")
    start = datetime(2026, 10, 10, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 0, 0, 0, tzinfo=tz)

    articles = collector.collect(start, end)
    assert articles == []


def test_ge_collector_registry() -> None:
    collectors = get_collectors()
    assert any(c.name == "ge" for c in collectors)
