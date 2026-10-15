# Identidade visual Urubu News

- **Data:** 2026-10-15
- **Status:** entregue, com a logo gerada no Nano Banana
- **ADRs:** —

## Objetivo

Trocar a marca "Flamengo News" por **Urubu News**, com logo e paleta próprias, para a newsletter
não parecer canal oficial do clube. O conteúdo continua sendo o Flamengo.

## Fora de escopo

- Remetente (`news@diegoponte.dev`) continua igual. O domínio mudou depois, em 2026-10-15: a página
  vive em `urubunews.diegoponte.dev`; `flamengo.diegoponte.dev` só redireciona a página inicial e
  segue atendendo os links (descadastro, confirmação, logo) dos e-mails já enviados.
- Renomear repositório, pacote `flanews`, imagem Docker e stack do `infra`.
- Escudos dos times no placar e na página de exemplo: são dado da partida, ficam.

## Contratos

- Nome: "Urubu News" no assunto (`Urubu News — <edição>: <manchete>`), remetente padrão,
  títulos, prompts, relatório e textos da página e dos e-mails.
- Paleta: carvão `#141414`, vermelho-urubu `#A51C24`, papel `#F4EFE6`, tinta `#1C1C1C`,
  cinza `#6B6B6B`. Fonte de títulos na página: Oswald (Google Fonts); e-mail usa a fonte do sistema.
- Arquivos em `src/flanews/web/static/`, servidos em `{PUBLIC_URL}/static/`:
  - `logo-email.png` (640×255, exibida a 320×127, sobre o papel; por isso o cabeçalho é claro);
  - `icon-512.png` (ícone sozinho, transparente fora do círculo: favicon, avatar do Gmail);
  - `og-image.png` (1200×630, prévia de link no LinkedIn/WhatsApp, `twitter:card=summary_large_image`).
  - Originais (Nano Banana) recortados e com paleta reduzida (31 KB e 17 KB).
- `render(..., logo_url=...)`: o cabeçalho da newsletter usa `<img src=logo_url alt="Urubu News">`.
- Rodapé da newsletter e da página: "Feito por um torcedor, sem ligação oficial com o clube."
- Ícone: urubu com cara de mau (mascote de time/e-sports), traço chapado e contorno forte,
  legível a 32 px, só cores da paleta, sem escudo ou listras de clube.

## Critérios de aceite (como testes)

- [x] `test_build_subject_with_and_without_headline`: assunto começa com "Urubu News —".
- [x] `test_render_header_uses_the_logo_image`: `<img src=logo_url alt="Urubu News">`, sem "FLAMENGO NEWS".
- [x] `test_render_footer_says_unofficial`: aviso de sem ligação oficial no HTML e no texto.
- [x] `test_static_logo_files_are_served`: `/static/logo-email.png` e `/static/icon-512.png` → 200 `image/png`.
- [x] `test_page_uses_the_brand_not_the_crest`: título, `og:image` e favicon com o ícone; escudo só no placar de exemplo.
- [x] `test_confirmation_email_uses_the_logo`: e-mail de confirmação com a logo e "Urubu News".

## Verificação ponta a ponta

```bash
uv run python -m flanews preview --edition monday --open   # cabeçalho com a logo
curl -sI https://urubunews.diegoponte.dev/static/icon-512.png   # depois do deploy
```

## Riscos e dúvidas abertas

- "Urubu" é o apelido da torcida; vale uma busca no INPI antes de investir mais na marca.
- Os segredos `NEWSLETTER_FROM` (GitHub) e `flamengo_news_sender` (`infra`) ainda dizem
  "Flamengo News": precisam ser trocados para o nome do remetente mudar.
- As imagens do cabeçalho dependem da VPS no ar; com imagens bloqueadas, aparece o `alt`.
