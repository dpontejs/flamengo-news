# Bolão da Urubu News

- **Data:** 2026-11-10
- **Status:** proposta
- **ADRs:** —

## Objetivo

Tornar o e-mail uma brincadeira de ida e volta entre os assinantes. O pré-jogo traz uma cartela de placares e o assinante crava o seu. O pós-jogo mostra quem acertou, o ranking da temporada e títulos zoeiros. Escolhas do dono: cartela 4×4 (layout B do brainstorm), em que o placar exato conta pontos. Projeto por diversão: o critério é ser gostoso de usar.

## Como funciona

- **Pré-jogo:**
  - A cartela 4×4 mostra os gols do Flamengo nas linhas e os do adversário nas colunas, de 0 a 3. As células são coloridas: verde para vitória, cinza para empate, vermelho para derrota.
  - Abaixo vem o link "Goleada? Outro placar".
  - Cada célula é um link pessoal: `/palpite?t=<token>&m=<match_id>&p=2-1`.
- **Clique:** abre uma página "Cravar Flamengo 2 x 1 Bahia?" com o botão **Confirmar**, que faz um POST.
  - *Decisão minha:* o GET não grava nada, porque antivírus de e-mail (Outlook Safe Links e similares) abrem todos os links da mensagem e gravariam palpites falsos.
  - Na primeira vez, a mesma página pede um apelido (3–20 caracteres, único). O ranking nunca mostra o e-mail.
  - Dá para trocar o palpite até o apito. Depois do apito, a página mostra "Bolão fechado" e o palpite registrado.
- **Pontos** (*decisão minha*, o dono aprovou):
  - placar exato: 5;
  - vencedor e saldo de gols certos: 3;
  - só o resultado (vitória, empate ou derrota): 2;
  - erro: 0.
  - Empate com placar errado (1x1 num jogo que terminou 0x0) vale 2: empate não tem vencedor, então a regra do saldo não se aplica (*decisão minha*).
  - O ranking é por temporada (ano civil); o desempate é por número de placares exatos.
- **Pós-jogo:** quadro "Bolão" com o placar real, os apelidos de quem cravou e o top 5 da temporada.
  - Títulos: "Rei do Maracanã" para o líder e "Pé-frio da rodada" para quem mais errou o saldo entre os que fizeram 0 ponto. Empate em pé-frio: ninguém leva.
  - Link "Ver ranking completo" para `/bolao?t=<token>`, onde a linha do próprio leitor aparece destacada.
- **Quem participa:** só os inscritos **ativos** pela página, porque o link precisa de token.
  - Os e-mails da lista fixa (`NEWSLETTER_RECIPIENTS`) recebem a edição sem a cartela, mas veem o quadro do pós-jogo, que não é pessoal, com o link do ranking sem token (*decisão minha*).
  - Quem se descadastra não aposta mais: `/palpite` mostra "inscrição inativa". Também sai do ranking (*decisão minha*).
- **Boas-vindas:** a edição guardada na página mantém os marcadores da cartela. Ao mandar a última edição para quem acabou de confirmar, a página gera o token dessa pessoa e preenche a cartela, então dá para apostar no jogo que ainda não começou (*decisão minha*).
- **Prévia e `DRY_RUN` não gravam nada na página:** `register_match()` e `report_result()` só rodam em envio real. A prévia e o dry-run usam o resumo calculado sem salvar (`GET …/summary`) (*decisão minha*).

## Fora de escopo

- A posição de cada leitor dentro do e-mail, o que exigiria conteúdo diferente por pessoa além dos links. Ela aparece na página do ranking.
- Joguinho, Memória rubro-negra, fóruns e prêmios.
- Palpite em jogo sem edição de pré-jogo.

## Contratos

- **Banco (SQLite da página, tabelas novas, `CREATE TABLE IF NOT EXISTS` sem migration):**
  - `bolao_matches(match_id PK, opponent, flamengo_home INT, kickoff TEXT, fla_goals INT NULL, opp_goals INT NULL)`;
  - `bolao_bets(email, match_id, fla_goals, opp_goals, updated_at, PK(email, match_id))`;
  - `bolao_players(email PK, nickname UNIQUE COLLATE NOCASE)`.
- **Tokens:** `make_token(secret, "bet", email, now)`, sem expiração; o fechamento é pelo apito.
- **Rotas da página:**
  - `GET /palpite` → página de confirmação. Token inválido → 400; jogo desconhecido → 404; bolão fechado → 200 com o palpite registrado.
  - `POST /palpite` (form `t, m, p, nickname?`) → 200 "Palpite registrado". Depois do apito → 409; apelido em uso → 409 com o formulário de novo.
  - `GET /bolao?t=` → ranking da temporada; sem token, ranking sem destaque.
- **API (Bearer `SUBSCRIBERS_API_TOKEN`):**
  - `GET /api/subscribers`: cada item ganha `bet_token`.
  - `PUT /api/bolao/matches/{match_id}` `{opponent, flamengo_home, kickoff}` → 204. É idempotente e atualiza o horário se o jogo for remarcado.
  - `GET /api/bolao/matches/{match_id}/summary?fla=&opp=` → 200 `BolaoSummary` calculado sem salvar
    (prévia e `DRY_RUN`).
  - `PUT /api/bolao/matches/{match_id}/result` `{fla_goals, opp_goals}` → 200 `BolaoSummary{exact: [str], top: [{nickname, points}], king: str|None, cold_foot: str|None}`. Idempotente.
- **Newsletter:**
  - `Recipient.bet_token: str | None`; o HTML usa `BET_TOKEN_PLACEHOLDER`, trocado por destinatário como o link de descadastro. Sem token, o bloco `<!--bolao-->…<!--/bolao-->` sai do e-mail.
  - Pré-jogo: `register_match()` antes do envio. Se falhar, o e-mail sai sem cartela e o problema vai para o relatório.
  - Pós-jogo: `report_result()` devolve o `BolaoSummary` e `Newsletter.bolao` o renderiza. Se falhar, o e-mail sai sem o quadro.

## Critérios de aceite (como testes)

- [ ] `test_bet_get_does_not_record`: dado um link válido, quando o GET é feito, então nenhum palpite é gravado e a página traz o botão Confirmar.
- [ ] `test_bet_post_records_and_overwrites_before_kickoff`: dois POSTs antes do apito deixam só o último palpite.
- [ ] `test_bet_after_kickoff_is_rejected`: um POST depois do `kickoff` responde 409 e o palpite anterior continua.
- [ ] `test_bet_token_cannot_bet_for_someone_else`: o token de A só grava palpites de A, porque o e-mail vem do token e não do formulário.
- [ ] `test_first_bet_requires_unique_nickname`: sem apelido → o formulário pede um; apelido repetido, com outra caixa → 409.
- [ ] `test_points_exact_5_diff_3_outcome_2_miss_0`: num jogo 2x1, os palpites 2x1, 3x2, 1x0, 2x0 e 0x0 valem 5, 3, 3, 2 e 0. Num jogo 0x0, os palpites 0x0, 1x1 e 1x0 valem 5, 2 e 0.
- [ ] `test_unsubscribed_cannot_bet_and_leaves_ranking`: depois do descadastro, o POST é recusado e a pessoa some do `/bolao`.
- [ ] `test_welcome_edition_fills_the_bet_token`: a edição de boas-vindas sai com os links do novo assinante, sem placeholder literal.
- [ ] `test_preview_and_dry_run_never_write_to_the_page`: a prévia e o dry-run não fazem PUT; usam o GET de resumo.
- [ ] `test_fixed_list_sees_post_game_board_without_token`: a lista fixa vê o quadro do pós-jogo, com o link do ranking sem token.
- [ ] `test_result_summary_is_idempotent`: o mesmo PUT de resultado feito duas vezes não duplica pontos e devolve o mesmo resumo.
- [ ] `test_match_reschedule_moves_the_deadline`: um PUT com novo `kickoff` reabre o bolão até o novo horário.
- [ ] `test_api_bolao_requires_token`: sem Bearer → 401.
- [ ] `test_pre_game_card_links_are_per_recipient`: cada destinatário recebe links com o seu `bet_token`; quem não tem token recebe o e-mail sem a cartela.
- [ ] `test_pre_game_sends_without_card_when_page_is_down`: com o PUT do jogo falhando, o e-mail é enviado sem a cartela.
- [ ] `test_post_game_renders_exact_top5_and_titles`: o pós-jogo mostra quem cravou, o top 5, o Rei do Maracanã e o Pé-frio.

## Verificação ponta a ponta

```bash
uv run pytest && uv run python -m flanews preview --edition pre --date <dia> --open
```

Com a página local, `uvicorn`, o fluxo é: clicar numa célula da prévia, confirmar, ver o palpite no `/bolao`, rodar o PUT de resultado e conferir o quadro no `preview --edition post`.

## Entrega em 2 PRs

1. **Página:** tabelas, `/palpite`, `/bolao`, API e `bet_token`.
2. **Newsletter:** cartela no pré-jogo, registro do jogo, resultado e quadro no pós-jogo.

## Riscos e dúvidas abertas

- O Gmail e o Outlook mostram a cartela 4×4 como tabela simples; precisa testar no celular, no Gmail app.
- O jogo pode ser remarcado depois do pré-jogo: o PUT seguinte atualiza o `kickoff`, e os palpites continuam valendo.
