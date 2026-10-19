# Urubu News

Newsletter automática sobre o Flamengo (feita por um torcedor, sem ligação oficial com o clube), enviada por e-mail **antes e depois de cada jogo** (pré-jogo, pós-jogo e, nos intervalos maiores, notícias), conforme a agenda da ESPN:

- **Notícias** do período, coletadas de várias fontes e resumidas por IA (Gemini).
- **Última partida** com placar, gols e estatísticas, e uma **Análise**: leitura do jogo por IA,
  forma recente, campanha no Brasileirão, rankings e destaques individuais.
- **Saiba mais** (outras modalidades do clube) e **Brasil afora** (futebol brasileiro), escolhidos
  pela IA só quando há algo relevante.
- **Próximo jogo** e **classificação**.

Quem quiser receber se inscreve em **[urubunews.diegoponte.dev](https://urubunews.diegoponte.dev)**,
confirma pelo e-mail e sai com um clique.

Arquitetura e decisões: [`docs/PLAN.md`](docs/PLAN.md). Backlog: [`docs/TASKS.md`](docs/TASKS.md).

## Como funciona

```
GitHub Actions (cron seg/sex 11:00 UTC)
  └─ python -m flanews run
       ├─ coleta: Google News, ge, site oficial + candidatos (extras e Brasil afora)
       ├─ estatísticas: API pública da ESPN (sem chave)
       ├─ IA: Gemini (4 chamadas por edição)
       ├─ render: HTML (CSS inline) + texto puro
       └─ envio: Resend (domínio próprio), um e-mail por inscrito
                 ▲
                 └─ GET /api/subscribers ── VPS: página de inscrição (FastAPI + SQLite)
```

As notícias não têm banco: cada edição olha a janela desde o envio anterior (pré-jogo 6 h antes
do apito, pós-jogo às 08:00 do dia seguinte, notícias quando o intervalo passa de 72 h; ver
`docs/features/edicoes-por-jogo.md`). Só a página de inscrição guarda dados (e-mails e a última
edição, num SQLite na VPS).

## Setup local

Requisitos: Python 3.12+ e [uv](https://github.com/astral-sh/uv).

```bash
uv sync
cp .env.example .env   # depois preencha as chaves (veja abaixo)
```

### Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | sim | chave do Google AI Studio |
| `GEMINI_MODEL` | não | padrão `gemini-flash-latest` |
| `RESEND_API_KEY` | para enviar | chave da Resend (permissão "Sending access" basta) |
| `NEWSLETTER_FROM` | para enviar | ex.: `"Flamengo News <news@seudominio.com>"` |
| `NEWSLETTER_RECIPIENTS` | para enviar | lista fixa, separada por vírgula (recebe sempre, mesmo com a página fora do ar) |
| `SUBSCRIBERS_API_TOKEN` | não | liga a página de inscrição: o envio busca os inscritos na API e o rodapé ganha o link |
| `PUBLIC_URL` | não | endereço da página de inscrição (padrão `https://urubunews.diegoponte.dev`) |
| `SUBSCRIBE_SECRET` | só na VPS | assina os links de confirmação e descadastro |
| `SUBSCRIBERS_DB` | só na VPS | caminho do SQLite (padrão `data/subscribers.db`) |
| `NOTIFY_EMAIL` | só na VPS | recebe um e-mail a cada inscrição confirmada (opcional) |
| `DRY_RUN` | não | padrão `true`: monta tudo mas não envia |
| `FLAMENGO_TEAM_ID` | não | id do Flamengo na ESPN (`819`) |
| `TIMEZONE` | não | padrão `America/Sao_Paulo` |

Para colar uma chave sem que ela apareça na tela ou no histórico do shell:

```bash
printf 'Chave: ' && read -rs T && echo && printf 'GEMINI_API_KEY="%s"\n' "$T" >> .env && unset T
```

## Chaves e contas

### Gemini (resumos e análise)

1. Em [aistudio.google.com](https://aistudio.google.com), crie um **projeto só para este app** e
   gere uma API key.
2. Use uma chave exclusiva: o plano gratuito do Flash permite **20 requisições/dia por modelo**, e
   cada edição usa 4. Compartilhar a chave com outros projetos pode esgotar a cota no dia do envio.
3. Se a cota acabar, a newsletter ainda sai, com títulos, links e estatísticas, mas sem os textos
   da IA.

### Resend (envio) + domínio na Cloudflare

1. Crie uma conta em [resend.com](https://resend.com) e gere uma API key com **Sending access**.
2. Em **Domains**, adicione o seu domínio (região `sa-east-1`) e use **Auto configure** para criar
   os registros na Cloudflare (DKIM `resend._domainkey` e os CNAMEs `send` e `rsend`). Deixe o
   proxy **desligado** (DNS only).
3. Recomendado: crie também o TXT `_dmarc` com `v=DMARC1; p=none;`.
4. Espere o status ficar **Verified**. Até lá, a API aceita o envio, mas ele falha depois com
   "Domain is not verified" (veja em Resend → Emails).
5. Para receber os pedidos de descadastro (o link do rodapé é um `mailto:`), configure na Cloudflare
   o **Email Routing** do endereço remetente para a sua caixa de entrada.

## Comandos

```bash
uv run python -m flanews collect --edition pre --date 2026-10-18  # lista as notícias coletadas
uv run python -m flanews stats   --edition pre --date 2026-10-18  # última partida, próximo jogo e tabela
uv run python -m flanews preview --edition pre --date 2026-10-18 --open  # gera out/preview-<data>.html
uv run python -m flanews run     --edition auto                  # monta e envia (respeita DRY_RUN)
```

- `--edition`: `pre`, `post`, `news` (com `--date`, a edição prevista naquele dia) ou `auto` (a que
  a agenda manda agora; sem nada vencido, sai sem enviar). `uv run python -m flanews due` mostra a
  edição vencida.
- `--date AAAA-MM-DD`: gera a edição de outra data.
- `run` sai com código 1 quando não há notícia nem partida (não envia newsletter vazia) e 2 quando
  o envio falha. Ao final, imprime um resumo da execução.

Primeiro envio real, só para você:

```bash
DRY_RUN=false NEWSLETTER_RECIPIENTS=voce@email.com uv run python -m flanews run --edition pre --date 2026-10-18
```

## Envio automático (GitHub Actions)

O timer `newsletter-trigger` da VPS (repositório `infra`) roda `flanews due` a cada 10 minutos e
dispara o workflow [`newsletter.yml`](.github/workflows/newsletter.yml) uma vez por edição. O
próprio workflow roda de hora em hora como reserva (`--edition auto --skip-if-sent`).

1. Cadastre os segredos do repositório a partir do `.env`, sem exibir os valores:

   ```bash
   for k in GEMINI_API_KEY RESEND_API_KEY NEWSLETTER_FROM NEWSLETTER_RECIPIENTS; do
     v=$(grep "^$k=" .env | cut -d= -f2- | sed 's/^"//;s/"$//'); gh secret set "$k" --body "$v"
   done
   ```

2. Opcional: defina a variável do repositório `GEMINI_MODEL` para trocar o modelo sem mexer no
   código.
3. Teste em **Actions → Newsletter → Run workflow**: o modo "Só simular" vem **ligado**. Ou pelo
   terminal:

   ```bash
   gh workflow run newsletter.yml -f edition=pre -f date=2026-10-18 -f dry_run=true
   ```

4. Cada execução publica um **resumo** na página da execução (notícias por fonte, tópicos, tokens
   do Gemini, falhas parciais e resultado) e guarda o HTML enviado como artifact por 30 dias.

Para mudar a lista fixa: `gh secret set NEWSLETTER_RECIPIENTS --body "a@x.com,b@y.com"`. Os demais
se inscrevem pela página; o resumo da execução mostra quantos vieram de lá.

O GitHub desativa workflows agendados após 60 dias sem commits no repositório; se isso acontecer,
reative na aba Actions.

## Página de inscrição

App FastAPI em [`src/flanews/web/`](src/flanews/web) que roda na VPS (stack `flamengo-news` do
repositório [`infra`](https://github.com/dpontejs/infra)), a partir da imagem
`ghcr.io/dpontejs/flamengo-news:main` publicada pelo CI.

- `/`: página com o formulário; `/subscribe` manda o e-mail de confirmação (link válido por 7 dias).
- `/unsubscribe`: o link do rodapé pede confirmação; o Gmail e outros usam o one-click (RFC 8058).
- `/api/subscribers`: lista dos ativos com o link de descadastro de cada um, protegida por
  `SUBSCRIBERS_API_TOKEN`; é o que o workflow lê antes de enviar.
- `/api/latest-edition`: depois de cada envio real, o workflow publica a edição aqui; quem
  confirma a inscrição recebe essa edição na hora, com o assunto "Boas-vindas! …".

Para rodar localmente (sem `RESEND_API_KEY`, o link de confirmação aparece no log):

```bash
SUBSCRIBE_SECRET=dev uv run uvicorn flanews.web.app:create_app --factory --reload
```

Plano grátis da Resend: 100 e-mails/dia. Como cada inscrito recebe o próprio e-mail, isso dá
uns 90 inscritos com folga para as confirmações.

## Personalizar

### Ajustar os textos da IA

Os prompts ficam em [`src/flanews/prompts/`](src/flanews/prompts) como templates Jinja2 em pt-BR:

| Arquivo | Gera |
|---|---|
| `group.md` | agrupamento das notícias em tópicos e escolha dos itens de "Saiba mais"/"Brasil afora" |
| `summarize.md` | resumo de cada tópico e a frase de cada item curto (uma única chamada) |
| `intro.md` | manchete e abertura da edição |
| `analysis.md` | leitura do jogo na seção "Análise" |

Depois de editar, confira com `preview` antes do próximo envio.

### Adicionar uma modalidade ao "Saiba mais"

Edite o dicionário `EXTRAS` em
[`src/flanews/collectors/candidates.py`](src/flanews/collectors/candidates.py). A chave é o nome da
etiqueta no e-mail e o valor é a busca no Google News:

```python
EXTRAS = {
    "Basquete": '"Flamengo" basquete OR NBB',
    "Vôlei": '"Sesc-Flamengo" OR "Flamengo" vôlei',
    "Futebol feminino": '"Flamengo" futebol feminino',
    "Remo": '"Flamengo" remo regata',  # exemplo
}
```

A IA escolhe no máximo 3 itens entre todas as modalidades, então uma modalidade nova só aparece
quando tem algo relevante.

### Adicionar uma fonte de notícias do Flamengo

Crie um coletor em `src/flanews/collectors/` com `name` e
`collect(start, end) -> list[Article]` (veja `ge.py`), registre-o em `get_collectors()` em
`collectors/base.py` e teste com uma fixture salva em `tests/fixtures/` usando `respx`. Os testes
nunca acessam a internet.

## Desenvolvimento

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Regras do repositório (commits, ordem das tasks, convenções): [`AGENTS.md`](AGENTS.md).

## Licença

[MIT](LICENSE). Vulnerabilidades: veja [SECURITY.md](SECURITY.md).
