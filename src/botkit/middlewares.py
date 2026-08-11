"""Middlewares: database sessions, user upsert, rate limiting, error trapping.

Order matters and is set in :mod:`botkit.bot`. Sessions first, because the user
upsert needs one; the upsert next, because rate limiting and permission checks
need a role; the throttle after that, so a banned user is still recorded.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .storage import Repository, Role

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Opens one session per update and commits it if the handler succeeded.

    One transaction per update is the behaviour handlers expect: a handler that
    raises halfway through leaves nothing half-written.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            data["repo"] = Repository(session)
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result


class UserMiddleware(BaseMiddleware):
    """Records the user and injects their row plus role into handler data."""

    def __init__(self, owner_ids: frozenset[int] = frozenset()) -> None:
        self.owner_ids = owner_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        repo: Repository = data["repo"]
        user = await repo.upsert(
            user_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            locale=tg_user.language_code,
        )

        # Owners are configured, not stored. A database restore or a bad UPDATE
        # must never be able to lock everyone out of their own bot.
        if tg_user.id in self.owner_ids and user.role != Role.OWNER:
            user = await repo.set_role(tg_user.id, Role.OWNER) or user

        data["user"] = user
        data["role"] = user.role
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """A sliding-window rate limit, per user.

    A sliding window rather than a fixed one: with fixed buckets a user can send
    the full allowance at 0.99 s and again at 1.01 s, sailing through at double
    the intended rate exactly when they are hammering the bot.

    Admins are exempt — the person cleaning up an incident should not be
    throttled by the tool they are cleaning it up with.
    """

    def __init__(self, limit: int = 5, window: float = 2.0) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._warned: set[int] = set()

    def allow(self, user_id: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        events = self._events[user_id]

        while events and now - events[0] > self.window:
            events.popleft()

        if len(events) >= self.limit:
            return False

        events.append(now)
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        role: Role | None = data.get("role")

        if tg_user is None or (role is not None and role.can_act_as(Role.ADMIN)):
            return await handler(event, data)

        if self.allow(tg_user.id):
            self._warned.discard(tg_user.id)
            return await handler(event, data)

        # Warn once per burst. Replying to every throttled message turns a rate
        # limit into a way to make the bot spam the user.
        if tg_user.id not in self._warned:
            self._warned.add(tg_user.id)
            i18n = data.get("i18n")
            text = i18n("throttled") if i18n else "Too fast — slow down a little."
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=False)

        return None


class ErrorMiddleware(BaseMiddleware):
    """Logs the exception, tells the user something went wrong, re-raises.

    Re-raising matters: swallowing here would hide failures from aiogram's own
    error handlers and from any monitoring wired into them. The user-facing
    message is a courtesy, not a substitute for handling the error.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            logger.exception("handler failed for %s", type(event).__name__)
            i18n = data.get("i18n")
            text = i18n("error") if i18n else "Something went wrong. Try again."
            try:
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
            except Exception:
                logger.warning("could not deliver the error message to the user")
            raise
