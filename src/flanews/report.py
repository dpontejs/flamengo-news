"""End-of-run summary, printed to the log and to GitHub's step summary."""

import logging

from pydantic import BaseModel, Field

MAX_PROBLEMS = 20
MAX_PROBLEM_CHARS = 200


class RunReport(BaseModel):
    """What an edition run collected, generated and did."""

    edition: str
    articles_by_source: dict[str, int] = Field(default_factory=dict)
    candidates: dict[str, int] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    learn_more: int = 0
    around_brazil: int = 0
    has_match: bool = False
    has_next_match: bool = False
    has_standings: bool = False
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    recipients: int = 0
    subscribers: int = 0
    problems: list[str] = Field(default_factory=list)
    outcome: str = ""

    def to_markdown(self) -> str:
        def check(value: bool) -> str:
            return "✅" if value else "—"

        def number(value: int) -> str:
            return f"{value:,}".replace(",", ".")

        lines = [f"## Urubu News — {self.edition}", "", f"**Resultado:** {self.outcome}", ""]
        lines += ["### Notícias coletadas", "", "| Fonte | Artigos |", "|---|---|"]
        lines += [f"| {source} | {count} |" for source, count in self.articles_by_source.items()]
        lines += [f"| **total** | {sum(self.articles_by_source.values())} |", ""]

        lines += ["### Conteúdo", ""]
        lines += [f"Tópicos ({len(self.topics)}):"] + [f"- {t}" for t in self.topics] + [""]
        learn_more_pool = self.candidates.get("saiba_mais", 0)
        brazil_pool = self.candidates.get("brasil", 0)
        lines += [
            f"- Saiba mais: {self.learn_more} de {learn_more_pool} candidatos",
            f"- Brasil afora: {self.around_brazil} de {brazil_pool} candidatos",
            f"- Última partida: {check(self.has_match)} · Próximo jogo: "
            f"{check(self.has_next_match)} · Classificação: {check(self.has_standings)}",
            f"- LLM: {self.llm_calls} chamadas, {number(self.input_tokens)} tokens de entrada, "
            f"{number(self.output_tokens)} de saída",
            f"- Destinatários: {self.recipients} ({self.subscribers} pela página de inscrição)",
            "",
            "### Falhas parciais",
            "",
        ]
        if not self.problems:
            lines.append("Nenhuma falha parcial.")
        else:
            shown = self.problems[:MAX_PROBLEMS]
            lines += [f"- `{p[:MAX_PROBLEM_CHARS]}`" for p in shown]
            if len(self.problems) > len(shown):
                lines.append(f"- … e mais {len(self.problems) - len(shown)}")
        return "\n".join(lines) + "\n"


class ProblemCollector(logging.Handler):
    """Collects WARNING/ERROR records emitted while the context is active."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(f"{record.levelname} {record.name}: {record.getMessage()}")

    def __enter__(self) -> "ProblemCollector":
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc: object) -> None:
        logging.getLogger().removeHandler(self)
