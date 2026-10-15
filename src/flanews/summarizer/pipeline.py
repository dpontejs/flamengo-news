import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

from flanews.models import Article, MatchStats, Topic
from flanews.summarizer.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

MAX_TOPICS = 8
MAX_ARTICLES_PER_TOPIC = 5
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


class GroupedTopic(BaseModel):
    title: str
    article_ids: list[int]
    importance: int


class GroupResponse(BaseModel):
    topics: list[GroupedTopic]


class SummaryResponse(BaseModel):
    summary: str


class IntroResponse(BaseModel):
    headline: str
    intro: str


class EditionSummary(BaseModel):
    """Result of the summarization stage of an edition."""

    headline: str = ""
    intro: str = ""
    topics: list[Topic] = []


def render_prompt(name: str, **context: object) -> str:
    return _env.get_template(f"{name}.md").render(**context)


def group_articles(articles: list[Article], llm: LLMClient) -> list[Topic]:
    """Ask the LLM to group articles into topics (without summaries yet).

    Ids are 1-based positions in `articles`; invalid or repeated ids are ignored
    and topics left without articles are dropped.
    """
    dates = [a.published_at for a in articles]
    prompt = render_prompt(
        "group",
        articles=articles,
        max_topics=MAX_TOPICS,
        start=min(dates).strftime("%d/%m/%Y"),
        end=max(dates).strftime("%d/%m/%Y"),
    )
    response = llm.generate_json(prompt, GroupResponse)

    topics: list[Topic] = []
    for grouped in response.topics:
        ids = [i for i in dict.fromkeys(grouped.article_ids) if 1 <= i <= len(articles)]
        if len(ids) < len(grouped.article_ids):
            logger.warning("Ignoring invalid article ids in topic %r", grouped.title)
        if not ids:
            continue
        topics.append(
            Topic(
                title=grouped.title,
                summary="",
                articles=[articles[i - 1] for i in ids],
                importance=min(max(grouped.importance, 1), 5),
            )
        )
    topics.sort(key=lambda t: t.importance, reverse=True)
    return topics[:MAX_TOPICS]


def summarize_topic(topic: Topic, llm: LLMClient) -> Topic:
    prompt = render_prompt(
        "summarize", title=topic.title, articles=topic.articles[:MAX_ARTICLES_PER_TOPIC]
    )
    response = llm.generate_json(prompt, SummaryResponse)
    return topic.model_copy(update={"summary": response.summary.strip()})


def write_intro(
    topics: list[Topic], last_match: MatchStats | None, llm: LLMClient, label: str
) -> IntroResponse:
    prompt = render_prompt("intro", topics=topics, last_match=last_match, label=label)
    return llm.generate_json(prompt, IntroResponse)


def summarize_edition(
    articles: list[Article],
    llm: LLMClient,
    last_match: MatchStats | None = None,
    label: str = "",
) -> EditionSummary:
    """Group articles into topics, summarize each one and write the opening.

    A topic whose summary fails is skipped; a grouping failure propagates.
    """
    topics: list[Topic] = []
    if articles:
        for topic in group_articles(articles, llm):
            try:
                topics.append(summarize_topic(topic, llm))
            except LLMError as e:
                logger.warning("Skipping topic %r: %s", topic.title, e)

    if not topics and last_match is None:
        return EditionSummary()

    intro = write_intro(topics, last_match, llm, label)
    return EditionSummary(headline=intro.headline.strip(), intro=intro.intro.strip(), topics=topics)
