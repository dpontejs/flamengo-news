"""Welcome box on top of the edition a new subscriber gets right after confirming.

Stored editions are already rendered (CSS inlined), so the box goes right below the header's red
stripe, the one row with `height="5"`; without it only the plain text gets the welcome.
"""

import re

WELCOME_TITLE = "Boas-vindas à Urubu News!"
WELCOME_TEXT = (
    "A newsletter segue a agenda do Flamengo: um pré-jogo no dia da partida, com escalações, "
    "palpites e onde assistir; um pós-jogo na manhã seguinte, com placar e análise; e, quando o "
    "intervalo entre os jogos é maior, um resumo das notícias. Abaixo vai a última edição, para "
    "você já ir lendo."
)
FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
BOX = (
    f"<tr><td style='font-family:{FONT}; padding:24px 24px 0 24px'>"
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
    "<td style='background-color:#F4EFE6; border-left:4px solid #A51C24; padding:12px 16px'>"
    "<p style='font-size:13px; font-weight:800; letter-spacing:1px; text-transform:uppercase; "
    f"color:#A51C24; margin:0 0 4px 0'>{WELCOME_TITLE}</p>"
    "<p style='font-size:15px; line-height:1.5; color:#1C1C1C; margin:0'>"
    f"{WELCOME_TEXT}</p></td></tr></table></td></tr>"
)
STRIPE_ROW = re.compile(r'height="5"[^>]*>.*?</tr>', re.DOTALL)


def add_welcome(html: str, text: str) -> tuple[str, str]:
    """The edition with the welcome box (HTML) and paragraph (text) on top."""
    welcomed_html = STRIPE_ROW.sub(lambda m: m.group(0) + "\n  " + BOX, html, count=1)
    return welcomed_html, f"{WELCOME_TITLE}\n{WELCOME_TEXT}\n\n{text}"
