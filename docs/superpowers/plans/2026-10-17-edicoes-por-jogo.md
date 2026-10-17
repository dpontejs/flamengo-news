# Edições guiadas pelos jogos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pré-jogo, pós-jogo e notícias agendados a partir da agenda da ESPN, no lugar de segunda/sexta.

**Architecture:** `flanews.schedule` (puro) transforma jogos + último envio real em slots; `flanews due`
diz qual slot venceu; `run --edition pre|post|news` monta a edição do slot. PR 1 só acrescenta (segunda
e sexta seguem no ar); PR 2 troca o `auto`, o cron do Actions e o timer da VPS.

**Tech Stack:** Python 3.12, typer, pydantic, httpx/respx, Jinja2; Ansible + systemd no `infra`.

**Spec:** `docs/features/edicoes-por-jogo.md`

## Global Constraints

- Fuso `America/Sao_Paulo`; datas sempre aware. Rótulos: `Pré-jogo — dd/mm/aaaa`, `Pós-jogo — …`, `Notícias — …`.
- No máximo 4 chamadas ao LLM por edição. Testes sem internet (`respx`). Commits `tipo: descrição`, sem trailer.
- Antes de cada commit: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

## Review Focus

- Remarcação depois de um envio: slots passados não podem reaparecer como vencidos (âncora = último envio real) → `test_due_ignores_slots_before_last_send` (Task 1).
- ESPN fora do ar no `due`: imprime nada e sai 0, sem traceback → `test_due_prints_nothing_when_espn_fails` (Task 4).
- Jogo de madrugada em UTC (`00:30Z` = 21:30 BRT do dia anterior): pré e pós no dia certo → `test_utc_midnight_kickoff_uses_local_date` (Task 1).
- Pós-jogo sem partida encerrada: sai 0 sem enviar → `test_post_without_finished_match_sends_nothing` (Task 5).
- Pré-jogo sem matérias de escalação/palpite: seção some, edição sai → `test_pre_game_hides_lineups_and_tips_when_absent` (Task 6).

---

## PR 1 — agenda e edições (`flamengo-news`, branch `feat/edicoes-por-jogo`)

### Task 1: agenda pura

**Files:** Create `src/flanews/schedule.py`, `tests/test_schedule.py`.

**Interfaces — Produces:**
```python
class Fixture(BaseModel):
    match_id: str; league: str; kickoff: datetime; time_valid: bool
    state: Literal["pre", "in", "post", "postponed"]; home: str; away: str
class Slot(BaseModel):
    kind: Literal["pre", "post", "news"]; send_at: datetime; window_start: datetime
    match_id: str | None = None; league: str | None = None; label: str
def plan(fixtures: list[Fixture], now: datetime, last_sent: datetime | None) -> list[Slot]
def due(slots: list[Slot], now: datetime, grace: timedelta = timedelta(hours=3)) -> Slot | None
```

- [ ] **Step 1: testes (red).** `test_plan_matches_the_real_october_calendar` usa os 5 jogos da spec + Athletico
  18/11 (`time_valid=False`), `now=17/10 12:00`, `last_sent=16/10 19:11`, e compara `(kind, send_at)`
  com a tabela da spec; as 3 notícias depois do Grêmio são 08/11, 12/11 e 15/11 às 08:00 (empate no
  arredondamento vai para o dia seguinte). Mais: `test_pre_game_never_before_8am_and_morning_kickoff_goes_the_night_before`
  (apito 10:00 → véspera 20:00; apito 12:00 → 08:00), `test_tbd_kickoff_gets_pre_game_at_8am_on_match_day`,
  `test_postponed_match_has_no_slots`, `test_no_news_when_gap_is_72h_or_less`,
  `test_long_gap_spreads_news_evenly`, `test_no_fixtures_means_weekly_monday_news` (a partir de
  `last_sent`, 4 semanas), `test_window_starts_at_previous_send` (1º slot: `last_sent`),
  `test_due_returns_slot_only_inside_grace_window`, `test_due_ignores_slots_before_last_send`,
  `test_utc_midnight_kickoff_uses_local_date`.
- [ ] **Step 2:** `uv run pytest tests/test_schedule.py` → falha de import.
- [ ] **Step 3: implementar.** Pré/pós por jogo (pós planejado mesmo no futuro, para medir intervalos);
  linha do tempo ordenada; para cada intervalo `a → b` (`a` = envio anterior, o primeiro é `last_sent`
  ou `now`), se `b − a > 72h`: `n = max(1, horas // 84)`, pontos `a + i·(b−a)/(n+1)` arredondados às
  08:00 mais próximas. Sem jogo em `now + 14 dias`: segundas 08:00. Slots com `send_at <= last_sent` saem.
- [ ] **Step 4:** testes verdes. **Step 5:** `git commit -m "feat: plan match-driven edition slots"`.

### Task 2: ESPN — agenda, campeonatos e prévia

**Files:** Modify `src/flanews/stats/espn.py`, `src/flanews/models.py`; Test `tests/test_espn.py`;
fixtures `tests/fixtures/espn_schedule_fixtures.json`, `tests/fixtures/espn_summary_preview.json`
(gravar das respostas reais de `teams/819/schedule?fixture=true` e `summary?event=401841269`, enxugadas).

**Interfaces — Produces:** `LEAGUES` + `bra.camp.carioca: "Carioca"`, `bra.supercopa_do_brazil:
"Supercopa"`, `fifa.cwc: "Mundial de Clubes"`;
`ESPNStatsClient.get_fixtures() -> list[Fixture]` (agenda com e sem `fixture=true`, todos os campeonatos,
`STATUS_POSTPONED` → `postponed`); `get_preview(match_id: str, league: str) -> MatchPreview | None`;
`class MatchPreview(BaseModel): home_form: list[FormResult]; away_form: list[FormResult];
head_to_head: list[FormResult]; head_to_head_summary: str` (resultados do ponto de vista do Flamengo).

- [ ] **Step 1: testes (red)** `test_get_fixtures_parses_state_time_valid_and_new_leagues`,
  `test_get_preview_reads_last_five_and_head_to_head` (Bahia: V V D D V; série 4-1),
  `test_get_preview_returns_none_on_error`. **Step 2:** red. **Step 3:** implementar. **Step 4:** verde.
- [ ] **Step 5:** `git commit -m "feat: read fixtures and match previews from espn"`.

### Task 3: último envio com data

**Files:** Modify `src/flanews/web/store.py`, `src/flanews/web/app.py`, `src/flanews/send/recipients.py`; Tests `tests/test_web_app.py`, `tests/test_recipients.py`.

**Produces:** `GET /api/latest-edition` → `{"subject": str, "published_at": str}`;
`latest_edition(settings, client=None) -> LatestEdition | None` (`subject`, `published_at: datetime`)
substitui `latest_edition_subject`; `_already_sent` passa a usá-la.

- [ ] Steps: `test_latest_edition_subject_after_publishing` passa a exigir `published_at`; testes do cliente
  adaptados; red → implementar → verde → `git commit -m "feat: expose when the latest edition was sent"`.

### Task 4: slot → edição e comando `due`

**Files:** Modify `src/flanews/edition.py`, `src/flanews/models.py`, `src/flanews/__main__.py`; Tests `tests/test_edition.py`, `tests/test_due_command.py`.

**Produces:** `Edition.kind` aceita também `pre|post|news`; `Edition.match_id`, `Edition.league` opcionais;
`edition_from_slot(slot: Slot) -> Edition` (`start=window_start`, `end=send_at`);
`resolve_match_edition(kind, day: date, fixtures, last_sent, now) -> Edition | None`;
CLI `due` imprime `"{kind}\t{send_at:%Y-%m-%d}\t{label}"` ou nada; `run`/`preview` aceitam `pre|post|news`
(slot daquele tipo com `send_at.date() == --date`; sem slot → mensagem e saída 1).

- [ ] Testes: `test_due_prints_the_due_slot`, `test_due_prints_nothing_when_nothing_is_due`,
  `test_due_prints_nothing_when_espn_fails`, `test_resolve_match_edition_picks_slot_of_that_day`,
  `test_run_pre_without_slot_that_day_exits_1`. Red → implementar → verde →
  `git commit -m "feat: add due command and match-driven edition kinds"`.

### Task 5: montagem por tipo

**Files:** Modify `src/flanews/pipeline.py`, `src/flanews/summarizer/pipeline.py`, `src/flanews/models.py`,
`src/flanews/__main__.py`; Create `src/flanews/prompts/preview.md`; Tests `tests/test_build_newsletter.py`, `tests/test_run_command.py`.

**Produces:** `Newsletter.preview: MatchPreview | None`, `Newsletter.lineups: str = ""`,
`Newsletter.tips: list[str] = []`; `write_preview(articles, next_match, llm) -> PreviewResponse(lineups: str, tips: list[str])`
(lê `content` das matérias; "não invente"; vazio se não houver).
Regras: `pre` → sem candidatos, sem `last_match`, `MAX_TOPICS=4`, `preview` + `write_preview` no lugar da
análise; `post` → sem candidatos; `news` → como hoje; `monday|friday` intocados.

- [ ] Testes: `test_pre_game_builds_preview_without_extras_or_analysis` (FakeLLM: 4 chamadas no máximo),
  `test_post_game_has_no_extras`, `test_news_has_extras`, `test_post_without_finished_match_sends_nothing`
  (run sai 0, Resend não chamado). Red → implementar → verde → `git commit -m "feat: build pre-game, post-game and news editions"`.

### Task 6: renderização do pré-jogo

**Files:** Modify `src/flanews/render/templates/newsletter.html.j2`, `newsletter.txt.j2`; Test `tests/test_renderer.py`.

- [ ] Testes: `test_pre_game_renders_form_head_to_head_lineups_and_tips` (blocos "O jogo", "Momento dos
  times", "Últimos confrontos", "Prováveis escalações", "Palpites" no HTML e no texto, nessa ordem, antes
  das notícias) e `test_pre_game_hides_lineups_and_tips_when_absent`. Red → implementar no estilo do bloco
  de "Última partida" → verde → `git commit -m "feat: render the pre-game edition"`.
- [ ] **Fechar PR 1:** `preview --edition pre --date 2026-10-18 --open` (conferir à mão), marcar critérios da
  spec, `git push -u origin feat/edicoes-por-jogo`, `gh pr create` (descrição sem atribuição a IA).

## PR 2 — troca do disparo (depois do merge do PR 1)

### Task 7: `auto` pelo calendário (`flamengo-news`)

- [ ] `run --edition auto` = slot de `due` agora (nada vencido → sai 0 sem gerar); remover `monday|friday`
  de `edition.py`, CLI e testes (migrar testes para `pre|post|news`); workflow: opções `auto, pre, post, news`,
  cron `23 * * * *` com `--skip-if-sent`; página: "Antes e depois de cada jogo do Flamengo" no lugar de
  "Segunda e sexta, às 8h" (`base.html.j2`, `index.html.j2`, `email/confirm.txt.j2` e `.html.j2`);
  README, PLAN §1/§10/§12. Teste `test_run_auto_without_due_slot_exits_without_building`.
  `git commit -m "feat: schedule editions from the match calendar"`.

### Task 8: timer de 10 min na VPS (`infra`, branch `feat/newsletter-due`, commits em pt-BR)

- [ ] `newsletter-trigger`: `due=$(docker compose -f {{ stacks_dir }}/flamengo-news/compose.yml exec -T flamengo-news python -m flanews due)`;
  vazio → sai 0; `label` já em `/var/lib/newsletter-trigger/dispatched` → sai 0; senão dispara
  `edition=<kind>, date=<data>, dry_run=false, skip_if_sent=true` e grava o `label`.
  Serviço: `User=deploy`, `StateDirectory=newsletter-trigger`, sem `DynamicUser`; timer `OnCalendar=*:0/10`.
  Testar o script com `docker` e `curl` falsos no `PATH` (vazio, novo, repetido). `make test && make lint`.
  `git commit -m "feat: dispara cada edição da newsletter quando a agenda manda"`; PR; após merge, `make configure`.
- [ ] Spec: `Status: entregue (PR #…)`.
