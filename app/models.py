"""ORM entities: ``User``, ``Category``, ``Expense``, ``Budget``.

All four models live together — small enough to read in one file. Money is
:class:`~decimal.Decimal` stored as ``NUMERIC(11, 2)`` (exact, no float drift); timestamps are
``TIMESTAMPTZ`` maintained by the ORM — ``created_at`` once at insert, ``updated_at`` on every
flush. Foreign keys encode the deletion rules: an in-use category cannot be dropped
(``category_id`` ``RESTRICT``, backing the service-level guard), while a user's rows and a
category's budgets cascade away. Uniqueness is DB-authoritative through the indexes below —
services catch the resulting ``IntegrityError`` and return 409.
"""

import datetime as dt
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# NUMERIC(11, 2) — 9 integer + 2 fraction digits — is exactly the 999,999,999.99 ceiling: the
# type itself rejects larger magnitudes and >2 decimals, so the per-table CHECKs only add the
# sign bound the type cannot express (expense > 0, budget >= 0).
_MONEY = Numeric(11, 2)


class User(Base):
    """A registered account that owns categories, expenses, and budgets.

    Email is stored lowercased and unique case-insensitively via ``uq_users_lower_email``.
    ``password_hash`` holds only the bcrypt hash — never plaintext, and never returned or
    logged. ``default_currency`` is editable only while the user has no expenses (enforced in
    the service).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    default_currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Case-insensitive email uniqueness: a functional unique index on lower(email), not a plain
# column UNIQUE (which would be case-sensitive). Auto-attaches to ``users``.
Index("uq_users_lower_email", func.lower(User.email), unique=True)


class Category(Base):
    """A spending category: a shared system default (``owner_id IS NULL``) or a user's own.

    System defaults are read-only and visible to everyone; custom categories belong to one
    user. Custom names are unique per owner case-insensitively via the partial index below; a
    collision against a null-owner default can't be one constraint, so the service checks it
    explicitly.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str] = mapped_column(String)  # short identifier (e.g. "food"); left unbounded
    color: Mapped[str] = mapped_column(String(7))  # "#RRGGBB"
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL for the shared system defaults; a user's id for custom categories. Custom rows
    # cascade away with their owner.
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Custom-category name uniqueness per owner, case-insensitive. Partial: only custom rows are
# constrained — system defaults share a NULL owner and are excluded.
Index(
    "uq_categories_owner_lower_name",
    Category.owner_id,
    func.lower(Category.name),
    unique=True,
    postgresql_where=Category.owner_id.isnot(None),
)


class Expense(Base):
    """A single spend by a user against one accessible category, in the owner's currency.

    ``currency`` is an immutable snapshot of the owner's ``default_currency`` at creation; the
    currency-change guard keeps it from ever diverging. ``receipt_url`` is stored and returned
    only — the server never fetches it (no SSRF surface).
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # RESTRICT is the DB backstop: the database refuses to drop a referenced category even
    # though the service checks first (so it can report the expense count).
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(_MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    date: Mapped[dt.date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))
    receipt_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # The expense response embeds its category; eager-load (selectinload) at query time so a
    # listing costs one category query per page, not one per row (avoids an N+1).
    category: Mapped["Category"] = relationship()

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),  # > 0
        # Date-filtered lists and per-month aggregation; the trailing ``date`` also serves the
        # date-DESC ordering, and (owner, category, date) covers category-filtered lists.
        Index("ix_expenses_owner_date", "owner_id", "date"),
        Index("ix_expenses_owner_category_date", "owner_id", "category_id", "date"),
    )


class Budget(Base):
    """A monthly spending limit for one category — at most one per (owner, category, year, month).

    Setting one that already exists updates it (an upsert keyed by the unique index below). A
    budget is removed with its category or its owner (``CASCADE``). Zero is allowed; negative
    is rejected by the CHECK.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(_MONEY)
    month: Mapped[int] = mapped_column(SmallInteger)
    year: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Budget responses embed the category too; eager-loaded at query time like expenses.
    category: Mapped["Category"] = relationship()

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_budgets_amount_nonneg"),  # >= 0: zero allowed
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_budgets_month_range"),
        # Matches the amount/month rigor: blocks year = 0 and other nonsense.
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_budgets_year_range"),
        # One budget per category per month; drives the INSERT ... ON CONFLICT upsert.
        UniqueConstraint(
            "owner_id", "category_id", "year", "month",
            name="uq_budgets_owner_category_year_month",
        ),
    )
