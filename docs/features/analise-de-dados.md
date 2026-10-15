# Análise de dados e redesign "placar de TV"

- **Data:** 2026-10-14
- **Status:** aprovada
- **ADRs:** —

## Objetivo

Dar à newsletter um diferencial além do resumo de notícias: uma seção "Análise" que interpreta a
última partida e o momento do time, e um visual com os escudos (CDN da ESPN) no lugar dos emojis.

## Fora de escopo

- Gráficos como imagem (continua no backlog).
- Barras comparativas nas estatísticas.
- Hospedar o escudo no repositório ou anexá-lo via CID (decidido: link do CDN da ESPN).

## Contratos

```python
# flanews.models
class MatchStats(BaseModel):  # campos novos
    home_logo: str | None = None
    away_logo: str | None = None
    leaders: dict[
        str, list[tuple[str, str, str]]
    ] = {}  # time -> [(categoria pt-BR, jogador, valor)]


class NextMatch(BaseModel):  # campo novo
    opponent_logo: str | None = None


class StandingRow(BaseModel):  # campos novos
    goals_for: int = 0
    goals_against: int = 0


class FormResult(BaseModel):
    result: Literal["V", "E", "D"]
    opponent: str
    score: str
    competition: str
    date: datetime


class PlayerRanking(BaseModel):
    category: str
    player: str
    position: int
    value: int  # ex.: ("Gols", "Pedro", 2, 16)


class TeamMoment(BaseModel):
    form: list[FormResult]  # últimos 5 jogos finalizados até o fim da janela
    standing: StandingRow | None  # linha do Flamengo no Brasileirão
    gap: str | None  # "1 ponto à frente do Palmeiras"
    rankings: list[PlayerRanking]  # jogadores do Flamengo no top 10 de gols/assistências


class Newsletter(BaseModel):  # campos novos
    analysis: str = ""  # leitura do jogo pelo LLM
    moment: TeamMoment | None = None
```

- `ESPNStatsClient.get_moment(end, standings) -> TeamMoment | None` (+1 requisição: `/{liga}/statistics`).
- `summarizer.pipeline.write_analysis(match, moment, llm) -> str` com o prompt `prompts/analysis.md`
  (+1 chamada; 4 por edição).
- Erros: falhas da ESPN degradam para `None`/`[]`; falha do LLM deixa `analysis = ""`.

## Critérios de aceite (como testes)

- [ ] `test_get_last_match_parses_logos_and_leaders`: dado o summary do Fla-Flu, então escudos e "Finalizações: Samuel Lino (3)".
- [ ] `test_get_next_match_includes_opponent_logo`: então o escudo do Estudiantes.
- [ ] `test_get_moment_form_and_rankings`: dado o fim da janela 12/10, então 5 resultados, o mais recente "V 1-0 Fluminense", e Pedro 2º em gols.
- [ ] `test_gap_for_leader_and_chaser`: líder → "N pontos à frente do 2º"; outro → "N pontos atrás do líder".
- [ ] `test_write_analysis_prompt_has_stats_and_form`: o prompt contém posse, gols e a forma.
- [ ] `test_build_newsletter_analysis_failure_keeps_moment`: LLM falha → `analysis == ""` e `moment` presente.
- [ ] `test_render_scoreboard_with_crests`: HTML com `<img>` dos dois escudos, `alt` preenchido e sem emojis 🔴⚫.
- [ ] `test_render_analysis_section`: forma em V/E/D, aproveitamento e destaques; some sem dados.

## Verificação ponta a ponta

```bash
uv run ruff check . && uv run pytest
GEMINI_MODEL=gemini-flash-lite-latest uv run python -m flanews preview --edition monday
```

Abrir `out/preview-2026-10-12.html` e conferir escudos, card do placar e a seção "Análise".

## Riscos e dúvidas abertas

- CDN e API da ESPN não são documentados; se mudarem, as imagens caem para o `alt` e a seção perde dados.
- Escudo é marca registrada: aceitável para uso pessoal, rever se virar produto.
