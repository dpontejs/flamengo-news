# Seções "Saiba mais" e "Brasil afora"

- **Data:** 2026-10-15
- **Status:** entregue (commit T17a, sem PR: trabalho direto na main)
- **ADRs:** —

## Objetivo

Ampliar a newsletter além do futebol masculino do Flamengo sem custo extra de LLM: até 3 notícias
de outras modalidades do clube ("Saiba mais") e até 5 do futebol brasileiro ("Brasil afora"),
escolhidas pelo LLM entre candidatos; as seções somem quando não há nada relevante.

## Fora de escopo

- Estatísticas de outras modalidades (a ESPN não cobre basquete brasileiro nem o feminino).
- Extras configuráveis por variável de ambiente (a lista fica em `collectors/candidates.py`).

## Contratos

```python
# flanews.collectors.candidates
EXTRAS: dict[str, str]          # modalidade -> busca no Google News
ExtrasCollector().collect(start, end) -> list[Article]   # section="saiba_mais", category=modalidade
BrazilCollector().collect(start, end) -> list[Article]   # section="brasil"; ge (geral + Série A) + Google News

# flanews.models
class Brief(BaseModel): title, summary, url, source, category
class Newsletter: learn_more: list[Brief]; around_brazil: list[Brief]

# flanews.summarizer.pipeline
GroupResponse.learn_more_ids / brazil_ids   # ids [S…]/[B…], no máx. 3 e 5
SummaryResponse.briefs: list[BriefSummary(item_id="S1", summary)]
summarize_edition(..., learn_more, brazil, extract)  # extract só nos escolhidos
```

- Orçamento: continua 4 chamadas ao LLM por edição; só os escolhidos (≤ 8) têm texto baixado.

## Critérios de aceite (como testes)

- [x] `test_picks_valid_ids_in_order_and_caps_each_section`, `test_only_picked_candidates_are_extracted`
- [x] `test_selection_keeps_llm_budget_at_three_calls` (+ análise = 4 por edição)
- [x] `test_brazil_collector_covers_whole_window_with_serie_a_feed` (feed geral cobre só ~23h)
- [x] `test_brazil_collector_keeps_news_that_only_mention_flamengo_in_summary` (exclusão só pelo título)
- [x] `test_extras_collector_drops_social_media_posts`
- [x] `test_render_learn_more_and_around_brazil_sections`, `test_render_hides_empty_short_sections`

## Verificação ponta a ponta

```bash
GEMINI_MODEL=gemini-flash-lite-latest uv run python -m flanews preview --edition monday
```

Edição de 12/10: "Saiba mais" com o bicampeonato do FlaBasquete; "Brasil afora" com calendário
2027, Dérbi e Série B 2027.

## Riscos e dúvidas abertas

- A busca do Google News traz ruído (ex.: futebol de cegos); a seleção do LLM filtra.
- Itens de redes sociais são descartados pela fonte; outros formatos ruins podem aparecer.
