# AGENTS.md — Regras para qualquer agente/modelo neste repositório

## Commits (OBRIGATÓRIO)
- Seguir **Conventional Commits**, **sem escopo**: `tipo: descrição` (ex.: `feat: add google news rss collector`).
- Tipos permitidos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`, `style`.
- Mensagem em **uma única frase**, numa única linha, sem corpo, sem ponto final.
- **Sem coautoria**: nunca adicionar `Co-authored-by:` nem qualquer trailer.
- Um commit por task (ou por unidade lógica dentro da task).

## Contexto do projeto
- Leia `docs/PLAN.md` (arquitetura e decisões) e `docs/TASKS.md` (backlog) antes de começar.
- Execute as tasks **na ordem** de `docs/TASKS.md`; marque `[x]` ao concluir cada uma.
- Não altere decisões de arquitetura do PLAN sem registrar o motivo na seção "Decisões" do PLAN.

## Stack e convenções de código
- Python 3.12, gerenciado com `uv`. Lint/format com `ruff`. Testes com `pytest`.
- Código, nomes e logs em inglês; conteúdo da newsletter e prompts em **pt-BR**.
- Segredos só via variáveis de ambiente (`.env` local, GitHub Secrets no CI). Nunca commitar `.env`.
- Toda chamada de rede deve ser mockável (`respx` para `httpx`); testes não acessam a internet.
- Antes de commitar: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
