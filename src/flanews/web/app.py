"""Subscription page: landing, sign-up with e-mail confirmation and one-click unsubscribe.

Run with `uvicorn flanews.web.app:create_app --factory`. Behind Caddy, start uvicorn with
`--proxy-headers` so the rate limit sees the visitor's IP.
"""

import hmac
import logging
import os
import re
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from flanews.config import Settings, get_settings
from flanews.send.resend_sender import UNSUBSCRIBE_PLACEHOLDER
from flanews.web.mailer import Mailer, MailError, mailer_from_settings
from flanews.web.store import RequestResult, SubscriberStore, normalize
from flanews.web.tokens import make_token, read_token
from flanews.web.welcome import add_welcome

logger = logging.getLogger(__name__)

CONFIRM_MAX_AGE = timedelta(days=7)
SIGNUPS_PER_IP = 5
SIGNUP_WINDOW = timedelta(hours=1)
# Deliberately strict: letters, digits and the usual symbols; dot-separated domain labels.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)
CONFIRMATIONS_PER_DAY = 30  # global cap: protects the Resend quota and the domain reputation
MAX_EMAIL_LENGTH = 254

WELCOME_PREFIX = "Boas-vindas! "

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class RateLimiter:
    """At most `limit` hits per key within `window` (in memory: one process, few users)."""

    def __init__(self, limit: int, window: timedelta) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)

    def allow(self, key: str, now: datetime) -> bool:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class EditionIn(BaseModel):
    subject: str
    html: str
    text: str


def is_valid_email(email: str) -> bool:
    return len(email) <= MAX_EMAIL_LENGTH and EMAIL_RE.match(email) is not None


def create_app(
    settings: Settings | None = None,
    store: SubscriberStore | None = None,
    mailer: Mailer | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    settings = settings or get_settings()
    secret = settings.SUBSCRIBE_SECRET
    if not secret:
        raise RuntimeError("SUBSCRIBE_SECRET is required to sign confirmation links")
    store = store or SubscriberStore(settings.SUBSCRIBERS_DB)
    mailer = mailer or mailer_from_settings(settings)
    limiter = RateLimiter(SIGNUPS_PER_IP, SIGNUP_WINDOW)
    public_url = settings.PUBLIC_URL.rstrip("/")

    def link(path: str, purpose: str, email: str) -> str:
        token = make_token(secret, purpose, email, now())
        return f"{public_url}{path}?{urlencode({'token': token})}"

    def page(request: Request, name: str, status: int = 200, **context) -> HTMLResponse:
        context.setdefault("public_url", public_url)
        return templates.TemplateResponse(request, name, context, status_code=status)

    def message(request: Request, title: str, text: str, status: int = 200, **extra):
        return page(request, "message.html.j2", status, title=title, text=text, **extra)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Logo and icon: used by the page, the confirmation e-mail and the newsletter header.
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
    def index(request: Request):
        return page(request, "index.html.j2")

    @app.get("/subscribe")
    def subscribe_reload():
        # Reloading the "check your inbox" page, or a link preview, lands here.
        return RedirectResponse("/", status_code=303)

    @app.get("/favicon.ico")
    def favicon():
        return RedirectResponse("/static/icon-512.png", status_code=301)

    @app.post("/subscribe", response_class=HTMLResponse)
    def subscribe(request: Request, email: str = Form(""), website: str = Form("")):
        check_inbox = (
            "Confira seu e-mail",
            "Se o endereço estiver certo, você vai receber um link para confirmar a inscrição. "
            "Não chegou? Dá uma olhada no spam.",
        )
        if website:  # honeypot: only bots fill the hidden field
            return message(request, *check_inbox)
        email = normalize(email)
        if not is_valid_email(email):
            return page(
                request, "index.html.j2", 400, error="Digite um e-mail válido.", email=email
            )
        client_ip = request.client.host if request.client else "unknown"
        if not limiter.allow(client_ip, now()):
            return message(
                request,
                "Muitas tentativas",
                "Espere um pouco e tente de novo.",
                status=429,
            )

        store.purge(now())
        if store.confirmations_sent_since(now() - timedelta(days=1)) >= CONFIRMATIONS_PER_DAY:
            logger.warning("Daily cap of %d confirmation e-mails reached", CONFIRMATIONS_PER_DAY)
            return message(
                request,
                "Muitas inscrições hoje",
                "Recebemos inscrições demais nas últimas horas. Tente de novo amanhã.",
                status=429,
            )
        if store.request(email, now()) is RequestResult.SEND_CONFIRMATION:
            try:
                mailer.send_confirmation(email, link("/confirm", "confirm", email))
            except MailError as e:
                logger.error("Confirmation e-mail failed: %s", e)
                store.forget_confirmation(email)
                return message(
                    request,
                    "Não deu para enviar",
                    "Não conseguimos enviar o e-mail de confirmação agora. Tente de novo em "
                    "alguns minutos.",
                    status=502,
                )
        return message(request, *check_inbox)

    @app.get("/confirm", response_class=HTMLResponse)
    def confirm(request: Request, token: str = ""):
        email = read_token(secret, "confirm", token, now(), max_age=CONFIRM_MAX_AGE)
        before = store.get(email) if email else None
        if email is None or not store.confirm(email, now()):
            return message(
                request,
                "Link inválido ou expirado",
                "Esse link de confirmação não vale mais. Faça a inscrição de novo na página "
                "inicial.",
                status=400,
            )
        # Only the first click welcomes: reopening the link must not resend the edition.
        first_time = before is not None and before.status == "pending"
        welcomed = first_time and send_latest_edition(email)
        text = "Pronto: você vai receber a Urubu News antes e depois de cada jogo do Flamengo."
        if welcomed:
            text += " Mandamos a última edição para o seu e-mail para você já ir lendo."
        return message(request, "Inscrição confirmada!", text + " Saudações rubro-negras!")

    def send_latest_edition(email: str) -> bool:
        edition = store.latest_edition()
        if edition is None:
            return False
        try:
            html, text = add_welcome(edition.html, edition.text)
            mailer.send_edition(
                email,
                WELCOME_PREFIX + edition.subject,
                html,
                text,
                link("/unsubscribe", "unsubscribe", email),
            )
        except MailError as e:
            logger.error("Welcome edition failed: %s", e)
            return False
        return True

    def unsubscribe_email(token: str) -> str | None:
        return read_token(secret, "unsubscribe", token, now())

    def invalid_unsubscribe(request: Request) -> HTMLResponse:
        return message(
            request,
            "Link inválido",
            "Não reconhecemos esse link de descadastro. Use o link do rodapé de uma edição.",
            status=400,
        )

    @app.get("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe_form(request: Request, token: str = ""):
        # GET only asks: e-mail scanners open links, and must not unsubscribe anyone.
        if unsubscribe_email(token) is None:
            return invalid_unsubscribe(request)
        return message(
            request,
            "Sair da lista?",
            "Você deixa de receber o Urubu News. Dá para voltar quando quiser.",
            unsubscribe_token=token,
        )

    @app.post("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe(request: Request, token: str = ""):
        # Also the RFC 8058 one-click target: the mail provider POSTs here directly.
        email = unsubscribe_email(token)
        if email is None:
            return invalid_unsubscribe(request)
        store.unsubscribe(email, now())
        return message(
            request,
            "Você foi descadastrado",
            "Não vai mais receber o Urubu News. Se mudar de ideia, é só se inscrever de novo.",
        )

    def authorized(request: Request) -> bool:
        expected = settings.SUBSCRIBERS_API_TOKEN
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())

    def unauthorized() -> JSONResponse:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)

    @app.get("/api/subscribers")
    def subscribers(request: Request):
        if not authorized(request):
            return unauthorized()
        return [
            {"email": email, "unsubscribe_url": link("/unsubscribe", "unsubscribe", email)}
            for email in store.active()
        ]

    @app.get("/api/latest-edition")
    def latest_edition(request: Request):
        # Lets a second trigger of the same run see that the edition already went out.
        if not authorized(request):
            return unauthorized()
        edition = store.latest_edition()
        if edition is None:
            return JSONResponse({"detail": "no edition published"}, status_code=404)
        return {
            "subject": edition.subject,
            "published_at": edition.published_at.isoformat(),
            "text": edition.text,  # the next run reads its topics to avoid repeating them
        }

    @app.put("/api/latest-edition", status_code=204)
    def publish_edition(request: Request, edition: EditionIn):
        # Published by the newsletter run after each real send; sent to new subscribers.
        if not authorized(request):
            return unauthorized()
        if UNSUBSCRIBE_PLACEHOLDER not in edition.html:
            return JSONResponse(
                {"detail": "html must contain the unsubscribe placeholder"}, status_code=422
            )
        store.set_latest_edition(edition.subject, edition.html, edition.text, now())
        return Response(status_code=204)

    @app.get("/version.json")
    def version():
        # The deploy check polls this until the new commit is live (infra: auto-deploy).
        commit = os.environ.get("GIT_SHA", "dev")
        return JSONResponse({"commit": commit}, headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        store.active()  # fails loudly if the database is unreachable
        return {"status": "ok"}

    return app
