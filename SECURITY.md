# Política de segurança

## Como reportar uma vulnerabilidade

Não abra uma issue pública. Use uma destas opções:

- **GitHub:** aba **Security → Report a vulnerability** deste repositório (relato privado).
- **E-mail:** diego@diegoponte.dev, com "segurança" no assunto.

Inclua o que encontrou, como reproduzir e o impacto que imagina. Respondo em até 7 dias; é um
projeto pessoal, sem programa de recompensa.

## Escopo

- O código deste repositório: coleta, geração e envio da newsletter (`src/flanews/`) e a página
  de inscrição (`src/flanews/web/`), publicada em https://urubunews.diegoponte.dev.
- A infraestrutura (VPS, Caddy, DNS) está no repositório
  [dpontejs/infra](https://github.com/dpontejs/infra).

Fora de escopo: ataques de negação de serviço, engenharia social e spam pelo formulário de
inscrição (ele tem limite por IP, limite diário e confirmação por e-mail).

## Dados

A página guarda só o e-mail e as datas de inscrição de quem se inscreve. Segredos (chaves do
Gemini e da Resend, tokens da API) ficam em GitHub Secrets e no `.env` da VPS, nunca no código.
