# Flamengo News — Backlog de Tasks

Instruções para o modelo que for executar:
- Leia `AGENTS.md` e `docs/PLAN.md` antes de qualquer task.
- Faça **uma task por vez, na ordem**. Ao terminar: rode lint + testes, marque `[x]` aqui e faça o commit sugerido (pode ajustar a descrição, mantendo o formato `tipo: frase única`, sem escopo, sem coautoria).
- Cada task lista **Arquivos**, **O que fazer**, **Aceite** e **Commit**.

---

## Fase 0 — Fundação

### [ ] T01 — Scaffold do projeto
- **Arquivos:** `pyproject.toml`, `src/flanews/__init__.py`, `src/flanews/__main__.py`, `.gitignore`, `.env.example`, `README.md`, `tests/test_smoke.py`
- **O que fazer:**
  - `uv init --package` (layout `src/`), Python 3.12, nome do pacote `flanews`.
  - Deps: `httpx feedparser selectolax trafilatura rapidfuzz google-genai jinja2 premailer pydantic pydantic-settings typer tenacity python-dateutil`.
  - Dev deps: `pytest respx ruff freezegun`.
  - Configurar `ruff` (line-length 100, regras `E,F,I,UP,B`) e `pytest` (`testpaths=["tests"]`) no `pyproject.toml`.
  - `__main__.py` com app `typer` e comando `version`.
  - `.env.example` igual à seção 8 do PLAN. `.gitignore` com `.env`, `.venv`, `out/`, `__pycache__`.
  - README curto: o que é, setup (`uv sync`), comandos.
- **Aceite:** `uv run python -m flanews version` imprime a versão; `uv run pytest` passa; `uv run ruff check .` limpo.
- **Commit:** `chore: scaffold python project with uv, ruff and pytest`

### [ ] T02 — Config e modelos
- **Arquivos:** `src/flanews/config.py`, `src/flanews/models.py`, `tests/test_config.py`
- **O que fazer:**
  - `Settings(BaseSettings)` com todas as envs do PLAN §8; `get_settings()` com `lru_cache`. Chaves opcionais (`API_FOOTBALL_KEY`, `RESEND_API_KEY`) podem ser `None`.
  - `models.py` (dataclasses ou pydantic): `Article`, `Topic(title, summary, articles: list[Article], importance)`, `MatchEvent`, `MatchStats(fixture_id, competition, date, home, away, home_goals, away_goals, venue, events, statistics: dict[str, tuple[str,str]], lineups)`, `NextMatch`, `StandingRow`, `Edition(kind, start, end, label)`, `Newsletter(edition, intro, topics, last_match, next_match, standings)`.
- **Aceite:** testes cobrindo leitura de env com `monkeypatch`.
- **Commit:** `feat: add settings and core domain models`

### [ ] T03 — Cálculo da edição (janela de datas)
- **Arquivos:** `src/flanews/edition.py`, `tests/test_edition.py`
- **O que fazer:**
  - `resolve_edition(kind: Literal["monday","friday","auto"], now: datetime) -> Edition`.
  - Segunda: janela sex 08:00 → seg 08:00. Sexta: seg 08:00 → sex 08:00. Tudo em `America/Sao_Paulo` (`zoneinfo`).
  - `auto`: seg→monday, sex→friday; outro dia → a edição mais recente que já passou (útil para testes manuais).
  - `label` em pt-BR: "Edição de Segunda — 13/10/2026".
- **Aceite:** testes com `freezegun` para seg, sex, quarta e virada de mês.
- **Commit:** `feat: add edition window resolution`

### [ ] T04 — CI
- **Arquivos:** `.github/workflows/ci.yml`
- **O que fazer:** em push/PR: `astral-sh/setup-uv`, `uv sync`, `ruff check`, `ruff format --check`, `pytest`.
- **Aceite:** YAML válido (`uv run python -c "import yaml"` não necessário; revisar manualmente).
- **Commit:** `ci: add lint and test workflow`

---

## Fase 1 — Coleta de notícias

### [ ] T05 — Interface de collector + Google News RSS
- **Arquivos:** `src/flanews/collectors/base.py`, `src/flanews/collectors/google_news.py`, `tests/fixtures/google_news.xml`, `tests/test_google_news.py`
- **O que fazer:**
  - `class Collector(Protocol): name: str; def collect(self, start, end) -> list[Article]`.
  - `get_collectors(settings) -> list[Collector]` (registry).
  - Cliente `httpx` compartilhado com `User-Agent: flanews/0.1 (+contato)` e timeout 15s.
  - Google News: baixar RSS do PLAN §3, parsear com `feedparser`, filtrar por `published` dentro da janela, `source` = nome do veículo (campo `source` do item) prefixado por `google_news:`.
  - Salvar um RSS real em `tests/fixtures/` (rodar uma vez manualmente) e testar com `respx`.
- **Aceite:** teste retorna artigos esperados e filtra por data.
- **Commit:** `feat: add google news rss collector`

### [ ] T06 — Collector ge.globo
- **Arquivos:** `src/flanews/collectors/ge.py`, `tests/fixtures/ge_flamengo.html`, `tests/test_ge.py`
- **O que fazer:**
  - Baixar `https://ge.globo.com/futebol/times/flamengo/`, inspecionar HTML e extrair manchetes (título, URL, data). Se a data não estiver na listagem, aceitar o artigo e deixar o filtro de data para a etapa de extração (ou buscar `article:published_time` no `<meta>` da página).
  - Checar `robots.txt` antes de implementar. Se o scraping for inviável, procurar RSS do ge e documentar no PLAN §12.
- **Aceite:** teste com fixture salva extrai ≥ 5 artigos com URL absoluta.
- **Commit:** `feat: add ge globo collector`

### [ ] T07 — Collector site oficial do Flamengo
- **Arquivos:** `src/flanews/collectors/flamengo_oficial.py`, fixture, teste
- **O que fazer:** igual à T06 para `https://www.flamengo.com.br/noticias` (verificar URL atual).
- **Aceite:** teste com fixture.
- **Commit:** `feat: add official flamengo site collector`

### [ ] T08 — Normalização, dedupe e extração de texto
- **Arquivos:** `src/flanews/processing/dedupe.py`, `src/flanews/processing/extract.py`, testes
- **O que fazer:**
  - `normalize_url` (remove `utm_*`, `fbclid`, fragment; resolve redirect do Google News seguindo redirects com `httpx`, ou extrair do HTML se necessário).
  - `dedupe(articles)`: por URL, depois por título com `rapidfuzz.fuzz.token_set_ratio >= 85`; prioridade de fonte: `flamengo_oficial > ge > google_news:*`.
  - `extract_content(article)`: baixa a página, usa `trafilatura.extract`, trunca em 4.000 chars, preenche `published_at` via metadata se estiver vazio. Falhas → mantém `summary_hint` e loga warning.
  - Paralelizar com `ThreadPoolExecutor(max_workers=5)` e rate-limit simples por domínio.
  - Filtro de relevância barato: título ou conteúdo deve conter "Flamengo", "Fla", "Mengão" ou "rubro-negro".
- **Aceite:** testes unitários para normalize/dedupe/filtro; extract testado com HTML fixture.
- **Commit:** `feat: add article normalization, dedupe and content extraction`

### [ ] T09 — Comando `collect`
- **Arquivos:** `src/flanews/__main__.py`, `src/flanews/pipeline.py`
- **O que fazer:** `collect_articles(edition, settings)` roda todos os collectors (erro em um não derruba os outros), dedupe, extract. Comando `collect` imprime tabela (fonte, data, título).
- **Aceite:** `uv run python -m flanews collect --edition monday` funciona com rede real (teste manual) e há teste do orquestrador com collectors fake.
- **Commit:** `feat: add collect command to run news collection pipeline`

---

## Fase 2 — Sumarização

### [ ] T10 — Cliente Gemini
- **Arquivos:** `src/flanews/summarizer/client.py`, `tests/test_llm_client.py`
- **O que fazer:**
  - Wrapper `LLMClient.generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel` usando `google-genai` (`client.models.generate_content` com `response_mime_type="application/json"` e `response_schema`).
  - Retry `tenacity` (3 tentativas, backoff exponencial) e validação pydantic.
  - Interface abstrata para permitir `FakeLLMClient` nos testes.
- **Aceite:** teste com fake/mocks; nenhum teste chama a API real.
- **Commit:** `feat: add gemini llm client with json output`

### [ ] T11 — Prompts e pipeline de sumarização
- **Arquivos:** `src/flanews/prompts/group.md`, `summarize.md`, `intro.md`, `src/flanews/summarizer/pipeline.py`, testes
- **O que fazer:** implementar as 3 etapas do PLAN §4.
  - `group`: entrada lista numerada de artigos; saída `{"topics":[{"title","article_ids","importance"}]}`, máx. 8 tópicos, ordenados por importância, descartando irrelevantes.
  - `summarize`: para cada tópico, 2–4 frases em pt-BR, tom jornalístico neutro, sem inventar.
  - `intro`: manchete + 2 frases resumindo a edição (recebe tópicos e resultado da última partida, se houver).
  - Prompts como templates Jinja2 lidos de arquivo.
- **Aceite:** teste com `FakeLLMClient` verifica montagem de `Topic`s e ids inválidos ignorados.
- **Commit:** `feat: add llm summarization pipeline with prompts`

---

## Fase 3 — Estatísticas

### [ ] T12 — Cliente API-Football
- **Arquivos:** `src/flanews/stats/api_football.py`, `tests/fixtures/api_football/*.json`, `tests/test_api_football.py`
- **O que fazer:**
  - Confirmar IDs (Flamengo, Brasileirão, Libertadores, Copa do Brasil) com `GET /teams?search=Flamengo&country=Brazil` e `GET /leagues?country=Brazil`; atualizar PLAN §5 se diferirem.
  - `get_last_match(start, end) -> MatchStats | None` (fixtures `last=3` → filtrar finalizado `FT/AET/PEN` na janela → buscar statistics, events, lineups).
  - `get_next_match() -> NextMatch | None`.
  - `get_standings(league_id, season) -> list[StandingRow]` (para Libertadores, pegar só o grupo do Flamengo).
  - Traduzir nomes das estatísticas para pt-BR (`Ball Possession` → `Posse de bola` etc.).
  - Sem chave → retorna `None` e loga info.
- **Aceite:** testes com JSON fixtures (salvar respostas reais uma vez) via `respx`.
- **Commit:** `feat: add api-football stats client`

### [ ] T13 — Comando `stats`
- **Arquivos:** `src/flanews/__main__.py`
- **O que fazer:** imprime última partida, próximo jogo e classificação da edição.
- **Aceite:** teste manual com chave real.
- **Commit:** `feat: add stats command`

---

## Fase 4 — Renderização e envio

### [ ] T14 — Template HTML e texto
- **Arquivos:** `src/flanews/render/renderer.py`, `src/flanews/render/templates/newsletter.html.j2`, `newsletter.txt.j2`, `tests/test_renderer.py`
- **O que fazer:**
  - Layout do PLAN §6, tabelas (não flex/grid), largura 600px, cores `#C3281E` (vermelho) e `#000`, fonte system.
  - `render(newsletter) -> tuple[html, text]`; CSS inline com `premailer`.
  - Seções opcionais somem se o dado for `None`.
- **Aceite:** teste com `Newsletter` fake gera HTML contendo placar, tópicos e links; snapshot simples opcional.
- **Commit:** `feat: add newsletter html and text templates`

### [ ] T15 — Comando `preview`
- **Arquivos:** `src/flanews/pipeline.py`, `src/flanews/__main__.py`
- **O que fazer:** `build_newsletter(edition, settings) -> Newsletter` (coleta + stats + sumarização) e `preview` grava `out/preview-<data>.html` e `.txt`. Opção `--open` abre no navegador.
- **Aceite:** gerar preview real e conferir visualmente.
- **Commit:** `feat: add preview command to render newsletter locally`

### [ ] T16 — Envio via Resend
- **Arquivos:** `src/flanews/send/resend_sender.py`, teste
- **O que fazer:**
  - `POST https://api.resend.com/emails` via `httpx` (sem SDK), `html` + `text`, assunto `"🔴⚫ Flamengo News — {label}: {manchete}"`.
  - Enviar com `to` = remetente e destinatários em `bcc` (ou um envio por destinatário se lista pequena).
  - Header `List-Unsubscribe` com `mailto:`.
  - `DRY_RUN=true` → não envia, só loga.
- **Aceite:** teste com `respx` verifica payload; dry-run não faz request.
- **Commit:** `feat: add resend email sender`

### [ ] T17 — Comando `run`
- **Arquivos:** `src/flanews/__main__.py`, `src/flanews/pipeline.py`
- **O que fazer:** `run --edition auto` = build + render + send; salva HTML em `out/`. Exit code ≠ 0 se não houver nenhuma notícia **e** nenhuma partida (não envia newsletter vazia).
- **Aceite:** teste end-to-end com tudo mockado.
- **Commit:** `feat: add run command for full newsletter delivery`

---

## Fase 5 — Produção

### [ ] T18 — Workflow agendado
- **Arquivos:** `.github/workflows/newsletter.yml`
- **O que fazer:** cron do PLAN §10 + `workflow_dispatch` com input `edition`; secrets `GEMINI_API_KEY`, `API_FOOTBALL_KEY`, `RESEND_API_KEY`, `NEWSLETTER_FROM`, `NEWSLETTER_RECIPIENTS`; `DRY_RUN=false`; upload de `out/` como artifact.
- **Aceite:** rodar manualmente via `workflow_dispatch` com dry-run primeiro.
- **Commit:** `ci: add scheduled newsletter workflow`

### [ ] T19 — Observabilidade e robustez
- **O que fazer:** logging estruturado (`logging` com níveis), resumo final no log (artigos coletados por fonte, tópicos, tokens usados se disponível), falhas parciais não abortam. Escrever resumo no `$GITHUB_STEP_SUMMARY`.
- **Commit:** `feat: add structured logging and run summary`

### [ ] T20 — Documentação final
- **O que fazer:** README com setup completo: criar chaves (Gemini AI Studio, API-Football, Resend + verificação de domínio), configurar secrets, rodar preview, ajustar prompts, adicionar nova fonte.
- **Commit:** `docs: document setup, secrets and usage`

---

## Backlog futuro (não fazer agora)
- [ ] Envio disparado N horas após o fim de cada jogo.
- [ ] Persistência (SQLite) para não repetir notícias entre edições.
- [ ] Página de inscrição/descadastro.
- [ ] Seções "Departamento médico" e "Mercado da bola".
- [ ] Gráfico de estatísticas como imagem.
