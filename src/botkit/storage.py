"""Persistence: users, roles and preferences.

SQLAlchemy 2.0 async, SQLite by default and Postgres by changing one URL. The
schema is small on purpose — a starter that ships an opinionated data model is a
starter you spend the first day deleting.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(enum.StrEnum):
    """What a user is allowed to do.

    Ordered deliberately: comparisons elsewhere rely on OWNER > ADMIN > USER,
    so a permission check is a comparison rather than a set of if-branches that
    someone will eventually get wrong.
    """

    BANNED = "banned"
    USER = "user"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return {
            Role.BANNED: 0,
            Role.USER: 1,
            Role.ADMIN: 2,
            Role.OWNER: 3,
        }[self]

    def can_act_as(self, required: Role) -> bool:
        return self.rank >= required.rank


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    # Telegram IDs exceed 32 bits, so BigInteger is not optional. SQLite does
    # not care; Postgres will reject the row, and only in production.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="")
    locale: Mapped[str | None] = mapped_column(String(8))
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=16), default=Role.USER
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.role}>"


class Repository:
    """Data access, kept out of the handlers.

    Handlers that build their own queries drift: one forgets to filter banned
    users, another writes a subtly different upsert. One place to change is
    worth the indirection.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def upsert(
        self,
        user_id: int,
        username: str | None = None,
        full_name: str = "",
        locale: str | None = None,
    ) -> User:
        """Create or refresh a user on every interaction.

        Deliberately does not touch ``role`` or ``locale`` on an existing row:
        this runs on every update, and an admin would be demoted to USER on
        their next message.
        """
        user = await self.get(user_id)
        if user is None:
            user = User(
                id=user_id, username=username, full_name=full_name, locale=locale
            )
            self.session.add(user)
        else:
            user.username = username
            user.full_name = full_name
            user.last_seen_at = utcnow()

        await self.session.flush()
        return user

    async def set_role(self, user_id: int, role: Role) -> User | None:
        user = await self.get(user_id)
        if user is None:
            return None
        user.role = role
        await self.session.flush()
        return user

    async def set_locale(self, user_id: int, locale: str) -> User | None:
        user = await self.get(user_id)
        if user is None:
            return None
        user.locale = locale
        await self.session.flush()
        return user

    async def locale_of(self, user_id: int) -> str | None:
        user = await self.get(user_id)
        return user.locale if user else None

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(User)) or 0

    async def count_by_role(self) -> dict[Role, int]:
        rows = await self.session.execute(
            select(User.role, func.count()).group_by(User.role)
        )
        return {role: count for role, count in rows}

    async def recipients(self) -> list[int]:
        """Everyone a broadcast may reach — banned users excluded."""
        rows = await self.session.execute(
            select(User.id).where(User.role != Role.BANNED)
        )
        return list(rows.scalars())


def make_engine(url: str, echo: bool = False):
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False so a handler can still read an object's attributes
    # after commit — otherwise every access triggers a lazy reload against a
    # session that may already be closed.
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine) -> None:
    """Create tables directly.

    For tests and a first run only. Real deployments use the Alembic migrations
    in ``migrations/`` — ``create_all`` cannot alter an existing table, so the
    second schema change is where a project that relied on it gets stuck.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
