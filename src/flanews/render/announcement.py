"""One-off e-mails to subscribers (format changes, notices), outside the edition schedule.

The source is a small Markdown subset: `# subject` on the first line, blank-line separated
paragraphs, `- ` list items and `**bold**`.
"""

import logging
import re

from markupsafe import Markup, escape
from premailer import Premailer
from pydantic import BaseModel

from flanews.render.renderer import DEFAULT_LOGO_URL, _env

BOLD = re.compile(r"\*\*(.+?)\*\*")


class Announcement(BaseModel):
    subject: str
    blocks: list[list[str]]  # paragraphs and lists, one line per item


def parse_announcement(source: str) -> Announcement:
    first, _, rest = source.strip().partition("\n")
    if not first.startswith("# "):
        raise ValueError("The first line must be the subject: '# ...'")
    blocks = [
        [line.strip() for line in block.splitlines() if line.strip()]
        for block in re.split(r"\n\s*\n", rest.strip())
    ]
    # "Intro:\n- item" is a paragraph followed by a list.
    split: list[list[str]] = []
    for block in blocks:
        head = [line for line in block if not line.startswith("- ")]
        items = [line for line in block if line.startswith("- ")]
        split += [b for b in ([" ".join(head)], items) if b and b != [""]]
    return Announcement(subject=first[2:].strip(), blocks=split)


def _bold(value: str) -> Markup:
    return Markup(BOLD.sub(r"<strong>\1</strong>", str(escape(value))))


def _plain(value: str) -> str:
    return BOLD.sub(r"\1", value)


def render_announcement(
    announcement: Announcement,
    unsubscribe_url: str | None = None,
    subscribe_url: str | None = None,
    logo_url: str = DEFAULT_LOGO_URL,
) -> tuple[str, str]:
    """Render as (html with inlined CSS, plain text), with the newsletter's header and footer."""
    context = {
        "a": announcement,
        "bold": _bold,
        "plain": _plain,
        "logo_url": logo_url,
        "unsubscribe_url": unsubscribe_url,
        "subscribe_url": subscribe_url,
    }
    html = _env.get_template("announcement.html.j2").render(**context)
    text = _env.get_template("announcement.txt.j2").render(**context)
    inlined = Premailer(
        html, keep_style_tags=False, remove_classes=True, cssutils_logging_level=logging.CRITICAL
    ).transform()
    return "<!doctype html>\n" + inlined, text.strip() + "\n"
