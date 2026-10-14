# Flamengo News 🔴⚫

Sistema automatizado de curadoria de notícias e estatísticas do Clube de Regatas do Flamengo, com sumarização via IA e envio de newsletter por e-mail toda segunda e sexta-feira.

## Requisitos

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

## Instalação e Setup

Clone o repositório e sincronize o ambiente virtual:

```bash
uv sync
```

Copie as variáveis de ambiente e configure as chaves necessárias:

```bash
cp .env.example .env
```

## Uso

Execute o CLI do `flanews`:

```bash
# Verificar versão
uv run python -m flanews version

# Ajuda
uv run python -m flanews --help
```

## Testes e Lint

```bash
# Rodar testes
uv run pytest

# Verificar lint e formatação
uv run ruff check .
uv run ruff format --check .
```
