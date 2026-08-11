"""Alembic environment.

Reads the URL from the same setting the bot uses, so migrations cannot be run
against a different database than the one the application talks to.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from botkit.storage import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.getenv("BOT_DATABASE_URL", "sqlite+aiosqlite:///botkit.db")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most columns in place; batch mode recreates the
        # table instead. Without it, the first non-trivial migration fails on
        # every developer's local database.
        render_as_batch=url.startswith("sqlite"),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_async())
