"""Wiring: build the dispatcher, attach middlewares in the right order, run.

The middleware order is the only thing here that is subtle, and it is load-
bearing — see :func:`setup_middlewares`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from .config import Settings
from .handlers import admin, common, feedback
from .i18n import I18nMiddleware, Translator
from .middlewares import (
    DatabaseMiddleware,
    ErrorMiddleware,
    ThrottleMiddleware,
    UserMiddleware,
)
from .storage import Repository, create_schema, make_engine, make_session_factory

logger = logging.getLogger(__name__)


def build_storage(settings: Settings):
    """Redis when configured, memory otherwise.

    Memory storage loses every in-progress form on restart. Acceptable in
    development, which is why the fallback exists at all — but a production
    deploy without Redis means a deploy interrupts every user mid-conversation.
    """
    if settings.redis_url:
        return RedisStorage.from_url(settings.redis_url)
    logger.warning("no BOT_REDIS_URL: FSM state will not survive a restart")
    return MemoryStorage()


def setup_middlewares(
    dispatcher: Dispatcher, settings: Settings, session_factory, translator: Translator
) -> None:
    """Attach middlewares. Order is the whole point.

    1. **Errors** outermost, so it sees failures from everything inside it.
    2. **Database**, because everything below needs a session.
    3. **User**, which needs the session and produces the role.
    4. **i18n**, which reads the user's stored locale.
    5. **Throttle** innermost, so a rate-limited user is still recorded, still
       has a role, and still gets the warning in their own language.

    Putting the throttle first would be the intuitive choice and would break all
    three of those.
    """

    async def locale_getter(user_id: int) -> str | None:
        async with session_factory() as session:
            return await Repository(session).locale_of(user_id)

    layers = [
        ErrorMiddleware(),
        DatabaseMiddleware(session_factory),
        UserMiddleware(owner_ids=settings.owner_ids),
        I18nMiddleware(translator, locale_getter=locale_getter),
        ThrottleMiddleware(
            limit=settings.throttle_limit, window=settings.throttle_window
        ),
    ]

    for layer in layers:
        dispatcher.message.middleware(layer)
        dispatcher.callback_query.middleware(layer)


def build_dispatcher(settings: Settings, session_factory) -> Dispatcher:
    translator = Translator.from_directory(
        settings.locales_dir, default=settings.default_locale
    )

    dispatcher = Dispatcher(storage=build_storage(settings))
    # Made available to handlers by name, which is how `translator` reaches the
    # language switcher without a global.
    dispatcher["translator"] = translator
    dispatcher["settings"] = settings

    setup_middlewares(dispatcher, settings, session_factory, translator)

    # Admin first: its router filters on role, so non-admins fall through to the
    # common handlers. Registering it after would let a generic /stats handler
    # shadow the admin one.
    dispatcher.include_router(admin.router)
    dispatcher.include_router(feedback.router)
    dispatcher.include_router(common.router)

    return dispatcher


async def run() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    await create_schema(engine)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings, session_factory)

    me = await bot.get_me()
    logger.info("starting @%s (id %s)", me.username, me.id)

    try:
        await dispatcher.start_polling(
            bot, drop_pending_updates=settings.drop_pending_updates
        )
    finally:
        # Ordered shutdown: stop the session, then the engine. Leaving either
        # open makes the process hang instead of exiting.
        await bot.session.close()
        await engine.dispose()
        logger.info("stopped")


def main() -> None:
    # Ctrl-C is how this process is meant to stop; a traceback on a normal
    # shutdown just trains people to ignore tracebacks.
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(run())


if __name__ == "__main__":
    main()
