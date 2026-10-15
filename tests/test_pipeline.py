from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import respx
from typer.testing import CliRunner

from flanews import pipeline
from flanews.__main__ import app
from flanews.models import Article, Edition
from flanews.processing.extract import DomainRateLimiter

TZ = ZoneInfo("America/Sao_Paulo")
EDITION = Edition(
    kind="monday",
    start=datetime(2026, 10, 9, 8, 0, tzinfo=TZ),
    end=datetime(2026, 10, 12, 8, 0, tzinfo=TZ),
    label="Edição de Segunda — 12/10/2026",
)


def make_article(url: str, title: str, source: str, day: int = 10) -> Article:
    return Article(
        url=url, title=title, source=source, published_at=datetime(2026, 10, day, 12, tzinfo=TZ)
    )


class FakeCollector:
    def __init__(self, name: str, articles: list[Article]) -> None:
        self.name = name
        self._articles = articles

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        return self._articles


class BrokenCollector:
    name = "broken"

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        raise RuntimeError("site down")


def page(text: str, published: str | None = None) -> httpx.Response:
    meta = f'<meta property="article:published_time" content="{published}">' if published else ""
    body = f"<p>{text} " * 5 + "</p>"
    return httpx.Response(
        200, text=f"<html><head>{meta}</head><body><article>{body}</article></body></html>"
    )


def run(collectors: list) -> list[Article]:
    with httpx.Client() as client:
        return pipeline.collect_articles(
            EDITION, collectors=collectors, client=client, limiter=DomainRateLimiter(0)
        )


@respx.mock
def test_collect_articles_survives_broken_collector() -> None:
    respx.get("https://ge.globo.com/1").mock(return_value=page("O Flamengo venceu o clássico."))
    articles = run(
        [
            BrokenCollector(),
            FakeCollector("ge", [make_article("https://ge.globo.com/1", "Flamengo vence", "ge")]),
        ]
    )
    assert [a.url for a in articles] == ["https://ge.globo.com/1"]
    assert articles[0].content


@respx.mock
def test_collect_articles_dedupes_across_collectors() -> None:
    respx.get("https://ge.globo.com/1").mock(return_value=page("O Flamengo venceu o clássico."))
    articles = run(
        [
            FakeCollector(
                "google_news",
                [
                    make_article(
                        "https://ge.globo.com/1?utm_source=gn",
                        "Flamengo vence - ge",
                        "google_news:ge",
                    )
                ],
            ),
            FakeCollector("ge", [make_article("https://ge.globo.com/1", "Flamengo vence", "ge")]),
        ]
    )
    assert [a.source for a in articles] == ["ge"]


@respx.mock
def test_collect_articles_drops_irrelevant_and_out_of_window() -> None:
    respx.get("https://x.com/irrelevante").mock(return_value=page("O Palmeiras treinou hoje."))
    respx.get("https://x.com/fora").mock(
        return_value=page("O Flamengo treinou hoje.", published="2026-10-12T09:30:00-03:00")
    )
    respx.get("https://x.com/ok").mock(return_value=page("O Mengão treinou hoje."))
    articles = run(
        [
            FakeCollector(
                "ge",
                [
                    make_article("https://x.com/irrelevante", "Treino no CT", "ge"),
                    make_article("https://x.com/fora", "Treino de segunda", "ge", day=12),
                    make_article("https://x.com/ok", "Treino de sábado", "ge"),
                ],
            )
        ]
    )
    assert [a.url for a in articles] == ["https://x.com/ok"]


@respx.mock
def test_collect_articles_sorts_newest_first() -> None:
    respx.get("https://x.com/a").mock(return_value=page("Flamengo A."))
    respx.get("https://x.com/b").mock(return_value=page("Flamengo B."))
    articles = run(
        [
            FakeCollector(
                "ge",
                [
                    make_article("https://x.com/a", "Flamengo treina", "ge", day=10),
                    make_article("https://x.com/b", "Pedro volta aos treinos", "ge", day=11),
                ],
            )
        ]
    )
    assert [a.url for a in articles] == ["https://x.com/b", "https://x.com/a"]


def test_collect_command_prints_table(monkeypatch) -> None:
    captured = {}

    def fake_collect(edition: Edition) -> list[Article]:
        captured["edition"] = edition
        return [make_article("https://ge.globo.com/1", "Flamengo vence o Palmeiras", "ge")]

    monkeypatch.setattr(pipeline, "collect_articles", fake_collect)
    result = CliRunner().invoke(app, ["collect", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    assert captured["edition"].label == "Edição de Segunda — 12/10/2026"
    assert "Flamengo vence o Palmeiras" in result.output
    assert "ge" in result.output
    assert "10/10" in result.output
