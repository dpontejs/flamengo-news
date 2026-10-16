# Imagens nas notícias e barras de estatísticas da partida

- **Data:** 2026-10-16
- **Status:** entregue (Issue #8)
- **ADRs:** —

## Objetivo

Tornar a newsletter mais visual com a imagem de destaque (`og:image`) das matérias principais
nos tópicos e barras visuais comparativas diretamente em HTML/CSS para as estatísticas da última partida
(na paleta de cores da Urubu News, estilo Google Sports/SofaScore).

## Decisão sobre gráficos

Inicialmente foi testada a geração de imagem PNG via Matplotlib. A abordagem foi descartada pelos seguintes motivos:
- Redundância: repetia os números já presentes no texto.
- Glitches visuais: sobreposição de texto em nomes longos de clubes e barras curtas.
- Peso: dependências pesadas de Matplotlib/C-libs (~60MB) desnecessárias no container/VPS.
- Acessibilidade e nitidez: barras em HTML nativo (`<table>` com porcentagens e cores `#A51C24` e `#141414`) renderizam com nitidez perfeita em qualquer resolução, sem bloqueio de imagens e com peso zero.

Além disso, foram adicionadas métricas defensivas disponíveis na API do ESPN (`effectiveTackles` para desarmes e `interceptions` para interceptações).

## Contratos

```python
# flanews.models
class Article(BaseModel):
    image_url: str | None = None  # HTTPS og:image extraída do HTML


class Topic(BaseModel):
    image_url: str | None = None  # herda automaticamente de articles[0].image_url
```

- `extract_content`: extrai `<meta property="og:image" content="...">` ignorando URLs não-HTTPS.
- `flanews.render.renderer`:
  - `_stat_shares(values: tuple[str, str]) -> tuple[int, int]`: calcula proporções home/away `(home_pct, away_pct)`.
- Paleta usada nas barras:
  - Vermelho-urubu: `#A51C24` (Flamengo)
  - Carvão: `#141414` (adversário)
  - Trilha de fundo: `#EFEBE4`
- E-mail HTML:
  - `<img>` dos tópicos com `width="512"` e `height="268"`, `alt` preenchido com o título do tópico.
  - Tabela comparativa com barras de 6px proporcionais e destaque em negrito para a equipe líder em cada quesito.
  - Layout preservado quando imagens estiverem bloqueadas no cliente de e-mail.

## Critérios de aceite (como testes)

- [x] `test_topic_uses_og_image_of_main_article` e `test_topic_without_image_keeps_layout`
- [x] `test_extract_content_ignores_non_https_image`
- [x] `test_stat_shares` e `test_render_match_stats_bars`
- [x] `test_preview_command_renders_match_stats_bars` e `test_run_renders_match_stats_in_email`

## Verificação ponta a ponta

```bash
uv run python -m flanews preview --edition monday --open
```
Conferir no navegador a imagem do tópico de destaque e as barras comparativas de estatísticas.
