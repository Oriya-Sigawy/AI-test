"""Database infrastructure: declarative ``Base``, engine, session factory, ``get_db``.

Imports no domain models, so the dependency flows ``models -> database`` only.
Schema creation and the default-category seed need the ORM models, so they live
in ``app.main`` startup rather than here.
"""

from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in ``app.models``."""


engine = create_engine(settings.database_url)
"""Engine for ``DATABASE_URL``; uses SQLAlchemy's default connection pool."""

SessionLocal = sessionmaker(bind=engine)
"""Session factory bound to ``engine``."""


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped Session and close it when the request ends.

    FastAPI dependency. Services own their commits; ``close()`` discards any
    open transaction, so a failed request leaves nothing persisted.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
