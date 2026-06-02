"""FastAPI application and composition root.

Builds the app and wires it together: turns on structured logging, installs the request-id
middleware and the shared error handlers, and on startup creates the database schema and
seeds the built-in categories. Being the top of the import graph, this is the only module
that imports the ORM models directly (so table creation registers every table); each
resource router is registered here as it is added.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import DEFAULT_CATEGORIES, settings
from app.database import Base, SessionLocal, engine
from app.errors import install_error_handlers
from app.logging_config import configure_logging, request_id_var
from app.models import Category
from app.routers import auth, budgets, categories, expenses, reports

logger = logging.getLogger(__name__)


def seed_default_categories(db: Session) -> None:
    """Create any built-in categories that are missing; safe to run on every startup.

    db -- an open session; the caller is responsible for committing.
    Only names not already present as a shared system category (one with no owner) are
    inserted, so restarting the app never creates duplicate defaults.
    """
    existing = set(db.scalars(select(Category.name).where(Category.owner_id.is_(None))).all())
    added = 0
    for category in DEFAULT_CATEGORIES:
        if category["name"] not in existing:
            db.add(Category(is_system=True, owner_id=None, **category))
            added += 1
    if added:
        logger.info("seeded default categories", extra={"event": "startup_seed", "added": added})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize logging, create the schema, and seed the built-in categories at startup.

    Runs once before the app accepts requests. Table creation skips tables that already exist
    and the seed is idempotent, so restarting the app is safe. This assumes a single starting
    process; if several workers start at once they could race, in which case schema setup
    should move to a dedicated migration/startup step.
    """
    configure_logging()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_default_categories(db)
        db.commit()
    logger.info("application startup complete", extra={"event": "startup"})
    yield


class RequestIdMiddleware:
    """Tag every HTTP request with a unique id so all of its log records can be correlated.

    A pure-ASGI middleware, so the id it stores in the request-scoped context variable is
    visible to everything handling the request in the same task — the dependencies, the
    endpoint, and the error handlers — and is attached to each log line automatically.

    It deliberately does not clear the id when the request ends: the handler for unexpected
    500 errors runs in an outer layer of the middleware stack, so clearing it here would drop
    the id from exactly the error log that needs it most. Setting a fresh id on entry already
    makes each request's id correct, and each request runs in its own context, so ids never
    leak between requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id_var.set(uuid.uuid4().hex)
        await self.app(scope, receive, send)


def _docs_urls(enabled: bool) -> dict[str, str | None]:
    """Return the docs/redoc/OpenAPI URL kwargs for ``FastAPI(...)``.

    When docs are disabled all three are ``None``, so a hardened deployment serves neither the
    interactive consoles (``/docs``, ``/redoc``) nor the schema (``/openapi.json``) — OWASP A05.
    """
    if not enabled:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


app = FastAPI(
    title="Personal Expense Tracker API",
    version="0.1.0",
    lifespan=lifespan,
    **_docs_urls(settings.enable_docs),
)
app.add_middleware(RequestIdMiddleware)
install_error_handlers(app)

# Resource routers are registered here as they are added.
app.include_router(auth.router)
app.include_router(categories.router)
app.include_router(expenses.router)
app.include_router(budgets.router)
app.include_router(reports.router)
