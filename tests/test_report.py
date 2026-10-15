import logging

from flanews.report import ProblemCollector, RunReport


def test_report_markdown_lists_counts_problems_and_outcome() -> None:
    report = RunReport(
        edition="Edição de Segunda — 12/10/2026",
        articles_by_source={"google_news": 9, "ge": 3, "flamengo_oficial": 1},
        candidates={"saiba_mais": 37, "brasil": 17},
        topics=["Fla-Flu", "Lesão do Danilo"],
        learn_more=3,
        around_brazil=5,
        has_match=True,
        has_next_match=True,
        has_standings=True,
        llm_calls=4,
        input_tokens=30500,
        output_tokens=1200,
        recipients=3,
        subscribers=2,
        problems=["WARNING flanews.processing.extract: Failed to extract content from x"],
        outcome="enviada (id=abc)",
    )

    md = report.to_markdown()

    assert md.startswith("## Urubu News — Edição de Segunda — 12/10/2026")
    assert "**Resultado:** enviada (id=abc)" in md
    assert "| google_news | 9 |" in md and "| **total** | 13 |" in md
    assert "Saiba mais: 3 de 37 candidatos" in md
    assert "Brasil afora: 5 de 17 candidatos" in md
    assert "- Fla-Flu" in md
    assert "LLM: 4 chamadas, 30.500 tokens de entrada, 1.200 de saída" in md
    assert "Última partida: ✅" in md
    assert "Destinatários: 3 (2 pela página de inscrição)" in md
    assert "Failed to extract content from x" in md


def test_report_without_problems_says_so() -> None:
    md = RunReport(edition="E", outcome="não enviada (DRY_RUN)").to_markdown()

    assert "Nenhuma falha parcial." in md
    assert "Última partida: —" in md


def test_problem_collector_captures_warnings_and_errors_only() -> None:
    logger = logging.getLogger("flanews.test")
    with ProblemCollector() as problems:
        logger.info("tudo certo")
        logger.warning("fonte fora do ar")
        logger.error("falhou %s", "resumo")
    logger.warning("depois do bloco")

    assert problems.messages == [
        "WARNING flanews.test: fonte fora do ar",
        "ERROR flanews.test: falhou resumo",
    ]
