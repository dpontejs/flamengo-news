from test_renderer import full_newsletter

from flanews.render.renderer import render
from flanews.web.welcome import WELCOME_TITLE, add_welcome


def test_welcome_box_goes_right_below_the_header_stripe() -> None:
    html, text = render(full_newsletter())

    welcomed_html, welcomed_text = add_welcome(html, text)

    stripe = welcomed_html.index('height="5"')
    box = welcomed_html.index(WELCOME_TITLE)
    headline = welcomed_html.index(full_newsletter().headline)
    assert stripe < box < headline
    assert welcomed_html.count(WELCOME_TITLE) == 1
    assert "pré-jogo" in welcomed_html and "pós-jogo" in welcomed_html
    assert welcomed_text.startswith(WELCOME_TITLE)
    assert welcomed_text.endswith(text)


def test_without_the_stripe_only_the_text_gets_the_welcome() -> None:
    html, text = add_welcome("<p>Fla</p>", "Fla")

    assert html == "<p>Fla</p>"
    assert text.startswith(WELCOME_TITLE) and text.endswith("Fla")
