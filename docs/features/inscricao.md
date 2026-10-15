# Página de inscrição e descadastro

- **Data:** 2026-10-15
- **Status:** entregue (commits T21–T24; deploy em dpontejs/infra#13)
- **ADRs:** — (decisão registrada no PLAN §12)

## Objetivo

Qualquer pessoa (amigos, quem veio do post no LinkedIn; dezenas de inscritos) se inscreve numa
página pública, confirma pelo e-mail e se descadastra com um clique, sem eu mexer em segredo do
GitHub.

## Fora de escopo

- Painel administrativo, estatísticas de abertura, preferências (só segunda ou só sexta).
- Backup do SQLite: depende do item "Shared database and backups" do repositório `infra`.
- Mover o envio do GitHub Actions para a VPS.

## Contratos

App FastAPI em `flanews.web` (`uvicorn flanews.web.app:create_app --factory`), atrás do Caddy em
`https://urubunews.diegoponte.dev` (`PUBLIC_URL`; antes `flamengo.diegoponte.dev`, que segue atendendo os links antigos).

```python
GET  /                     -> landing page com o formulário
POST /subscribe            form: email, website (honeypot) -> página "confira seu e-mail"
GET  /confirm?token=       -> ativa a inscrição; token vale 7 dias
GET  /unsubscribe?token=   -> página com botão de confirmação (scanners de link não descadastram)
POST /unsubscribe?token=   -> descadastra; também atende o one-click (RFC 8058)
GET  /api/subscribers      Authorization: Bearer <SUBSCRIBERS_API_TOKEN>
                           -> 200 [{"email": str, "unsubscribe_url": str}]
PUT  /api/latest-edition    Authorization: Bearer <SUBSCRIBERS_API_TOKEN>
                           json: subject, html, text (com o marcador de descadastro) -> 204
GET  /health               -> 200 {"status": "ok"}
```

- Banco: SQLite (`SUBSCRIBERS_DB`, volume Docker), tabela `subscribers(email PK, status
  pending|active|unsubscribed, created_at, confirmation_sent_at, confirmed_at, unsubscribed_at)`.
- Tokens: HMAC-SHA256 com `SUBSCRIBE_SECRET`, sem guardar nada; o de descadastro não expira.
- Sem enumeração: `/subscribe` responde a mesma página para e-mail novo, pendente ou ativo.
- Anti-abuso: honeypot, no máx. 5 inscrições por IP por hora, reenvio da confirmação só após 10 min.
- Envio (`run`): destinatários = `NEWSLETTER_RECIPIENTS` + `/api/subscribers` (quando
  `SUBSCRIBERS_API_TOKEN` existe), sem repetição. Falha na API: loga erro e envia só para a lista
  fixa. Um e-mail por pessoa via `POST /emails/batch` da Resend (até 100 por chamada), com
  `List-Unsubscribe` e `List-Unsubscribe-Post` próprios; a lista fixa usa o `mailto:`.
- Boas-vindas: o `run` publica a edição após cada envio real (falha só gera aviso); na primeira
  confirmação a VPS envia essa edição com assunto "Boas-vindas! …" e o link de descadastro da
  pessoa. Clicar de novo não reenvia; falha no envio não desfaz a inscrição.
- Erros: token inválido/expirado -> 400 com página amigável; API sem token correto -> 401.

## Critérios de aceite (como testes)

- [x] `test_subscribe_creates_pending_and_sends_confirmation`
- [x] `test_subscribe_same_page_for_active_email` (sem enumeração; não reenvia)
- [x] `test_subscribe_honeypot_and_invalid_email_send_nothing`
- [x] `test_subscribe_rate_limited_per_ip` e `test_confirmation_resend_cooldown`
- [x] `test_confirm_activates_and_is_idempotent`, `test_confirm_rejects_expired_or_forged_token`
- [x] `test_unsubscribe_get_does_not_unsubscribe`, `test_one_click_post_unsubscribes`
- [x] `test_resubscribe_after_unsubscribe_requires_confirmation`
- [x] `test_api_subscribers_requires_token_and_lists_only_active`
- [x] `test_sender_batches_one_email_per_recipient_with_own_unsubscribe_link`
- [x] `test_run_merges_static_and_api_recipients_and_survives_api_failure`
- [x] `test_first_confirmation_sends_the_latest_edition`, `test_clicking_the_confirmation_link_again_does_not_resend`
- [x] `test_run_publishes_the_edition_for_new_subscribers_after_a_real_send`, `test_dry_run_does_not_publish_the_edition`

## Verificação ponta a ponta

```bash
uv run uvicorn flanews.web.app:create_app --factory --port 8000   # inscrever, confirmar, descadastrar
docker build -t flanews . && docker run --rm -p 8000:8000 flanews  # healthcheck healthy
gh workflow run newsletter.yml -f dry_run=true   # resumo mostra quantos inscritos vieram da API
```

## Riscos e dúvidas abertas

- Plano grátis da Resend: 100 e-mails/dia. Com um e-mail por pessoa, cabe até ~90 inscritos.
- A VPS fora do ar no horário do envio: a edição sai só para a lista fixa (aparece no resumo).
