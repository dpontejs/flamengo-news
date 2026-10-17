import logging
from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field

from flanews.models import Article, Brief, MatchStats, NextMatch, TeamMoment, Topic
from flanews.summarizer.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

MAX_TOPICS = 8
MAX_PREVIEW_CHARS = 1500  # per article in the pre-game call
MAX_ARTICLES_PER_TOPIC = 5
LEARN_MORE_PICKS = 3
BRAZIL_PICKS = 5
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
    learn_more_ids: list[int] = Field(default_factory=list)
    brazil_ids: list[int] = Field(default_factory=list)


class TopicSummary(BaseModel):
    topic_id: int
    summary: str


class BriefSummary(BaseModel):
    item_id: str
    summary: str


class SummaryResponse(BaseModel):
    summaries: list[TopicSummary]
    briefs: list[BriefSummary] = Field(default_factory=list)


class IntroResponse(BaseModel):
    headline: str
    intro: str


class PreviewResponse(BaseModel):
    lineups: str = ""
    tips: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    analysis: str


class EditionSummary(BaseModel):
    """Result of the summarization stage of an edition."""

    headline: str = ""
    intro: str = ""
    topics: list[Topic] = []
    learn_more: list[Brief] = []
    around_brazil: list[Brief] = []


class Selection(BaseModel):
    """Topics plus the candidates the LLM picked for the short sections."""

    topics: list[Topic] = []
    learn_more: list[Article] = []
    brazil: list[Article] = []


def render_prompt(name: str, **context: object) -> str:
    return _env.get_template(f"{name}.md").render(**context)


def _pick(ids: list[int], candidates: list[Article], limit: int) -> list[Article]:
    """1-based ids into `candidates`, keeping order, dropping invalid and repeated ids."""
    valid = [i for i in dict.fromkeys(ids) if 1 <= i <= len(candidates)]
    return [candidates[i - 1] for i in valid[:limit]]


def group_articles(
    articles: list[Article],
    llm: LLMClient,
    learn_more: list[Article] | None = None,
    brazil: list[Article] | None = None,
    max_topics: int = MAX_TOPICS,
    published: list[str] | None = None,
    focus: NextMatch | None = None,
) -> Selection:
    """Group articles into topics and pick candidates for the short sections (1 call).

    Ids are 1-based positions in each list; invalid or repeated ids are ignored and
    topics left without articles are dropped.
    """
    learn_more, brazil = learn_more or [], brazil or []
    dates = [a.published_at for a in (*articles, *learn_more, *brazil)]
    prompt = render_prompt(
        "group",
        articles=articles,
        learn_more=learn_more,
        brazil=brazil,
        max_topics=max_topics,
        published=published or [],
        focus=focus,
        learn_more_picks=LEARN_MORE_PICKS,
        brazil_picks=BRAZIL_PICKS,
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
    return Selection(
        topics=topics[:max_topics],
        learn_more=_pick(response.learn_more_ids, learn_more, LEARN_MORE_PICKS),
        brazil=_pick(response.brazil_ids, brazil, BRAZIL_PICKS),
    )


def _brief(article: Article, summary: str) -> Brief:
    title = article.title
    prefix, _, outlet = article.source.partition(":")
    if prefix == "google_news" and outlet and title.endswith(f" - {outlet}"):
        title = title[: -len(f" - {outlet}")]  # Google News appends the outlet name
    return Brief(
        title=title,
        summary=summary,
        url=article.url,
        source=article.source,
        category=article.category,
    )


def summarize_selection(
    selection: Selection, llm: LLMClient
) -> tuple[list[Topic], list[Brief], list[Brief]]:
    """Summarize topics and short items in a single call (keeps within free-tier quotas).

    `topic_id` is the 1-based topic position and `item_id` is "S<n>"/"B<n>"; anything
    the model skips keeps an empty summary, and unknown ids are ignored.
    """
    topics = selection.topics
    prompt = render_prompt(
        "summarize",
        topics=[
            t.model_copy(update={"articles": t.articles[:MAX_ARTICLES_PER_TOPIC]}) for t in topics
        ],
        learn_more=selection.learn_more,
        brazil=selection.brazil,
    )
    response = llm.generate_json(prompt, SummaryResponse)
    by_id = {s.topic_id: s.summary.strip() for s in response.summaries}
    missing = [t.title for i, t in enumerate(topics, 1) if i not in by_id]
    if missing:
        logger.warning("No summary returned for topics: %s", missing)
    briefs = {b.item_id.strip().upper(): b.summary.strip() for b in response.briefs}
    return (
        [t.model_copy(update={"summary": by_id.get(i, "")}) for i, t in enumerate(topics, 1)],
        [_brief(a, briefs.get(f"S{i}", "")) for i, a in enumerate(selection.learn_more, 1)],
        [_brief(a, briefs.get(f"B{i}", "")) for i, a in enumerate(selection.brazil, 1)],
    )


def write_intro(
    topics: list[Topic],
    last_match: MatchStats | None,
    llm: LLMClient,
    label: str,
    next_match: NextMatch | None = None,
) -> IntroResponse:
    """`next_match` is set for the pre-game edition: the opening presents that match."""
    prompt = render_prompt(
        "intro", topics=topics, last_match=last_match, label=label, next_match=next_match
    )
    return llm.generate_json(prompt, IntroResponse)


def write_preview(articles: list[Article], match: NextMatch, llm: LLMClient) -> PreviewResponse:
    """Probable line-ups and the press's predictions, read from the pre-game articles' text."""
    prompt = render_prompt(
        "preview",
        match=match,
        articles=[a for a in articles if a.content],
        max_chars=MAX_PREVIEW_CHARS,
    )
    response = llm.generate_json(prompt, PreviewResponse)
    return PreviewResponse(
        lineups=response.lineups.strip(), tips=[t.strip() for t in response.tips if t.strip()]
    )


def write_analysis(match: MatchStats, moment: TeamMoment | None, llm: LLMClient) -> str:
    """'Leitura do jogo': the LLM interprets the match stats and the team's moment."""
    prompt = render_prompt(
        "analysis",
        m=match,
        moment=moment,
        goals=[e for e in match.events if e.type == "goal"],
        cards=[e for e in match.events if e.type == "red_card"],
    )
    return llm.generate_json(prompt, AnalysisResponse).analysis.strip()


def summarize_edition(
    articles: list[Article],
    llm: LLMClient,
    last_match: MatchStats | None = None,
    label: str = "",
    learn_more: list[Article] | None = None,
    brazil: list[Article] | None = None,
    extract: Callable[[list[Article]], list[Article]] | None = None,
    max_topics: int = MAX_TOPICS,
    next_match: NextMatch | None = None,
    published: list[str] | None = None,
) -> EditionSummary:
    """Group, pick short items, summarize everything and write the opening (3 LLM calls).

    Only the picked "Saiba mais"/"Brasil afora" candidates are passed to `extract`
    (text download). A grouping failure propagates; if the summaries or the opening
    fail, topics and picks are kept and the missing text stays empty.
    """
    selection = Selection()
    if articles or learn_more or brazil:
        selection = group_articles(
            articles, llm, learn_more, brazil, max_topics, published=published, focus=next_match
        )
        picks = [*selection.learn_more, *selection.brazil]
        if picks and extract is not None:
            extracted = extract(picks)
            n = len(selection.learn_more)
            selection = selection.model_copy(
                update={"learn_more": extracted[:n], "brazil": extracted[n:]}
            )

    topics = selection.topics
    lm_briefs = [_brief(a, "") for a in selection.learn_more]
    br_briefs = [_brief(a, "") for a in selection.brazil]
    if topics or lm_briefs or br_briefs:
        try:
            topics, lm_briefs, br_briefs = summarize_selection(selection, llm)
        except LLMError as e:
            logger.error("Summaries failed, keeping titles and sources: %s", e)

    if not topics and last_match is None and next_match is None:
        return EditionSummary(learn_more=lm_briefs, around_brazil=br_briefs)

    sections = {"topics": topics, "learn_more": lm_briefs, "around_brazil": br_briefs}
    try:
        intro = write_intro(topics, last_match, llm, label, next_match)
    except LLMError as e:
        logger.error("Opening failed: %s", e)
        return EditionSummary(**sections)
    return EditionSummary(headline=intro.headline.strip(), intro=intro.intro.strip(), **sections)
