# Edições guiadas pelos jogos (pré-jogo, pós-jogo, notícias)

- **Data:** 2026-10-17
- **Status:** proposta
- **ADRs:** —

## Objetivo

Trocar as edições fixas de segunda e sexta por três tipos que seguem o calendário do Flamengo:
**pré-jogo** (perspectivas no dia do jogo), **pós-jogo** (resultado e análise na manhã seguinte) e
**notícias** (noticiário e extras quando há intervalo longo entre jogos). Datas mudam e há períodos
sem jogo, então a agenda é recalculada a partir da ESPN, sem dias fixos. Todos recebem os três tipos.

## Fora de escopo

- Preferências por inscrito (caixas na página, página de preferências, e-mail de anúncio): projeto
  seguinte, que filtra por `kind` o que este entrega.
- Cotações de casas de apostas (a ESPN traz as da DraftKings): fora de propósito para a newsletter.
- Escalação oficial (só sai ~1 h antes do jogo) e envio durante o jogo.

## Regras da agenda (America/Sao_Paulo)

- **Jogos:** os da ESPN em `LEAGUES` (agenda com `fixture=true`). `LEAGUES` ganha o Carioca
  (`bra.camp.carioca`), a Supercopa (`bra.supercopa_do_brazil`) e o Mundial de Clubes (`fifa.cwc`).
  A tabela mostrada continua sendo a do Brasileirão em qualquer edição. *(decisão minha)*
- **Pré-jogo:** apito − 6 h, nunca antes das 08:00 do dia do jogo; apito antes das 11:00 → véspera às
  20:00. Horário ainda "a definir" no dia do jogo → 08:00.
- **Pós-jogo:** 08:00 do dia seguinte, só se a ESPN der a partida como encerrada; senão não sai.
- **Notícias:** quando entre o último envio e o próximo pré-jogo houver mais de 72 h,
  `n = max(1, intervalo_h // 84)` edições: o intervalo é dividido em `n + 1` partes iguais e cada ponto
  vai para as 08:00 do dia mais próximo. Sem jogo conhecido nos próximos 14 dias: uma por semana,
  segunda às 08:00; quando um jogo entra no horizonte, vale a regra do intervalo. *(decisão minha)*
- **Âncora no que já saiu** *(decisão minha)*: o intervalo e a janela de notícias partem do **último
  envio real** (`GET /api/latest-edition`, que passa a devolver `published_at`; usado pelo `due` e
  pelo `run`). Remarcações só movem slots futuros.
- Sem pós-jogo (adiado), o intervalo parte do último envio real; jogo com horário "a definir" conta
  como próximo jogo, com o pré-jogo previsto às 08:00 do dia dele. *(decisão minha)*
- **Janela de notícias** de cada edição: do último envio real até o envio dela.

## Conteúdo

- **Pré-jogo:** jogo (adversário, competição, horário, estádio); últimos 5 de cada time e últimos 5
  confrontos (`lastFiveGames`, `seasonseries` do `summary` da ESPN); prováveis escalações e palpites da
  imprensa extraídos das notícias pelo LLM (seção some se não houver); até 4 tópicos de futebol; tabela.
- **Pós-jogo:** a edição atual sem "Saiba mais" e "Brasil afora".
- **Notícias:** tópicos, "Saiba mais", "Brasil afora", próximo jogo e tabela.
- Assunto: `Urubu News — <Pré-jogo|Pós-jogo|Notícias> — dd/mm/aaaa: <manchete>`; continua com no máximo
  4 chamadas ao LLM (o pré-jogo troca a chamada de análise por uma de escalações e palpites, que lê o
  texto das matérias de pré-jogo).

## Contratos

```python
# flanews.schedule (puro, sem rede)
class Slot(BaseModel):
    kind: Literal["pre", "post", "news"]
    send_at: datetime          # aware, America/Sao_Paulo
    window_start: datetime     # janela de notícias
    match_id: str | None       # evento da ESPN (pre/post)
    label: str                 # "Pré-jogo — 18/10/2026"; chave de deduplicação
def plan(fixtures: list[Fixture], now: datetime) -> list[Slot]: ...
def due(slots: list[Slot], now: datetime, grace: timedelta = timedelta(hours=3)) -> Slot | None: ...
```

- `Edition.kind` passa a `Literal["pre", "post", "news"]`; somem `monday`/`friday`.
- CLI: `flanews due` imprime `kind send_at label` do slot vencido ou nada (saída 0);
  `flanews run --edition auto|pre|post|news [--date]` (auto = `due` agora; nada vencido → sai 0 sem
  gerar). `--skip-if-sent` e `--note` continuam.
- Workflow: `edition` com `auto, pre, post, news`; cron de reserva `23 * * * *` com `--skip-if-sent`.
- `infra`: `newsletter-trigger.timer` a cada 10 min roda, como `deploy`,
  `docker compose exec -T flamengo-news python -m flanews due`; se houver slot e o `label` não estiver
  em `/var/lib/newsletter-trigger/dispatched`, dispara `edition=<kind>` com `skip_if_sent=true` e grava
  o `label` (cada slot é disparado uma vez pela VPS; a reserva cobre falhas).

## Critérios de aceite (como testes)

- [ ] `test_plan_matches_the_real_october_calendar`: dados os jogos da ESPN em 17/10/2026 (abaixo),
  então os slots são exatamente estes:

  | Jogo (apito) | Pré-jogo | Pós-jogo | Notícias depois |
  |---|---|---|---|
  | Bahia, dom 18/10 18:30 | 18/10 12:30 | 19/10 08:00 | 21/10 08:00 |
  | Estudiantes, qui 22/10 21:30 | 22/10 15:30 | 23/10 08:00 | 25/10 08:00 |
  | Atlético-MG, seg 26/10 20:00 | 26/10 14:00 | 27/10 08:00 | — (≤ 72 h) |
  | Vasco, qui 29/10 20:00 | 29/10 14:00 | 30/10 08:00 | 02/11 08:00 |
  | Grêmio, qua 04/11 19:30 | 04/11 13:30 | 05/11 08:00 | 3 edições até o pré de 18/11 (horário a definir → 08:00) |
- [ ] `test_pre_game_never_before_8am_and_morning_kickoff_goes_the_night_before`.
- [ ] `test_tbd_kickoff_gets_pre_game_at_8am_on_match_day`.
- [ ] `test_no_post_game_when_match_not_finished` (adiado ou em andamento).
- [ ] `test_no_news_when_gap_is_72h_or_less` e `test_long_gap_spreads_news_evenly`.
- [ ] `test_no_fixtures_means_weekly_monday_news`.
- [ ] `test_due_returns_slot_only_inside_grace_window`.
- [ ] `test_pre_game_renders_form_head_to_head_lineups_and_tips` e
  `test_pre_game_hides_lineups_and_tips_when_absent`.
- [ ] `test_post_game_has_no_extras` e `test_news_has_extras`.
- [ ] `test_run_auto_without_due_slot_exits_without_building`.
- [ ] `test_skip_if_sent_uses_the_slot_label`.

## Verificação ponta a ponta

```bash
uv run python -m flanews due            # na VPS, via docker compose exec
uv run python -m flanews preview --edition pre --date 2026-10-18 --open
```
Primeira semana: conferir no Actions um run por slot e os de reserva terminando em "já enviada".

## Riscos e dúvidas abertas

- Resend grátis: 100 e-mails/dia e 3.000/mês. Com ~20 edições/mês, o limite chega perto de 150
  inscritos (hoje são 9); não entra neste projeto, vira issue quando passar de ~100.
- A ESPN não é documentada; se a agenda falhar, `due` não acha nada e a semana fica sem edição.
- Palpites e escalações dependem do que os portais publicam até o envio (jogo à noite: no próprio dia).
