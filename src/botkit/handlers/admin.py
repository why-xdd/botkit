"""Admin: statistics, role management, and a broadcast that will not melt.

The broadcast is the part worth reading. Sending to every user is where naive
bots get rate-limited into oblivion, so this paces itself, distinguishes a user
who blocked the bot from a real failure, and reports what actually happened.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..filters import HasRole, IsOwner
from ..i18n import BoundTranslator
from ..keyboards import admin_keyboard, broadcast_confirm_keyboard
from ..storage import Repository, Role

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(HasRole(Role.ADMIN))
router.callback_query.filter(HasRole(Role.ADMIN))

# Telegram's documented ceiling for broadcasts is about 30 messages per second.
# 25 leaves headroom for the bot's normal traffic, which is still being served
# while the broadcast runs.
BROADCAST_RATE = 25
BROADCAST_CHUNK = 25


class Broadcast(StatesGroup):
    message = State()
    confirm = State()


@router.message(Command("admin"))
async def admin_panel(message: Message, i18n: BoundTranslator) -> None:
    await message.answer(i18n("admin.panel"), reply_markup=admin_keyboard(i18n))


@router.message(Command("stats"))
@router.callback_query(F.data == "admin:stats")
async def stats(
    event: Message | CallbackQuery, repo: Repository, i18n: BoundTranslator
) -> None:
    counts = await repo.count_by_role()
    total = await repo.count()

    lines = [i18n("admin.stats.title"), i18n("admin.stats.total", count=total)]
    for role in (Role.OWNER, Role.ADMIN, Role.USER, Role.BANNED):
        lines.append(
            i18n("admin.stats.role", role=role.value, count=counts.get(role, 0))
        )
    text = "\n".join(lines)

    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.edit_text(text, reply_markup=admin_keyboard(i18n))
    else:
        await event.answer(text)


@router.message(Command("promote"), IsOwner())
async def promote(
    message: Message, command: CommandObject, repo: Repository, i18n: BoundTranslator
) -> None:
    """`/promote <user_id> <role>` — owners only.

    Owners only because an admin who can grant admin is effectively an owner,
    and the distinction between the roles would stop meaning anything.
    """
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer(i18n("admin.promote.usage"))
        return

    raw_id, raw_role = parts
    if not raw_id.lstrip("-").isdigit():
        await message.answer(i18n("admin.promote.bad_id"))
        return

    try:
        role = Role(raw_role.lower())
    except ValueError:
        await message.answer(
            i18n("admin.promote.bad_role", roles=", ".join(r.value for r in Role))
        )
        return

    if role is Role.OWNER:
        # Owners come from configuration, so granting the role here would create
        # an owner the config does not know about — and a restore would silently
        # revoke them.
        await message.answer(i18n("admin.promote.owner_is_config"))
        return

    user = await repo.set_role(int(raw_id), role)
    if user is None:
        await message.answer(i18n("admin.promote.unknown_user"))
        return

    await message.answer(i18n("admin.promote.done", user=user.id, role=role.value))


@router.message(Command("broadcast"))
@router.callback_query(F.data == "admin:broadcast")
async def begin_broadcast(
    event: Message | CallbackQuery, state: FSMContext, i18n: BoundTranslator
) -> None:
    await state.set_state(Broadcast.message)
    text = i18n("admin.broadcast.prompt")

    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.edit_text(text)
    else:
        await event.answer(text)


@router.message(Broadcast.message, F.text)
async def preview_broadcast(
    message: Message, state: FSMContext, repo: Repository, i18n: BoundTranslator
) -> None:
    await state.update_data(text=message.text)
    await state.set_state(Broadcast.confirm)

    recipients = await repo.recipients()
    await message.answer(
        i18n("admin.broadcast.preview", text=message.text, count=len(recipients)),
        reply_markup=broadcast_confirm_keyboard(i18n, len(recipients)),
    )


@router.callback_query(Broadcast.confirm, F.data == "broadcast:confirm")
async def send_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    repo: Repository,
    bot: Bot,
    i18n: BoundTranslator,
) -> None:
    data = await state.get_data()
    await state.clear()

    text = data.get("text", "")
    recipients = await repo.recipients()

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            i18n("admin.broadcast.started", count=len(recipients))
        )

    delivered, blocked, failed = await deliver(bot, recipients, text)

    if callback.message:
        await callback.message.answer(
            i18n(
                "admin.broadcast.finished",
                delivered=delivered,
                blocked=blocked,
                failed=failed,
            )
        )


async def deliver(bot: Bot, recipients: list[int], text: str) -> tuple[int, int, int]:
    """Send to everyone, paced, and report what happened.

    Returns ``(delivered, blocked, failed)``. The three are counted separately
    because they mean different things: *blocked* is users who removed the bot,
    which is normal attrition and not a fault, while *failed* is the number that
    should make someone look at the logs.
    """
    delivered = blocked = failed = 0

    for start in range(0, len(recipients), BROADCAST_CHUNK):
        chunk = recipients[start : start + BROADCAST_CHUNK]

        for user_id in chunk:
            try:
                await bot.send_message(user_id, text)
                delivered += 1
            except TelegramRetryAfter as exc:
                # Telegram is telling us the exact backoff. Obeying it and
                # retrying once is far better than dropping the message.
                logger.warning("rate limited, sleeping %ss", exc.retry_after)
                await asyncio.sleep(exc.retry_after)
                try:
                    await bot.send_message(user_id, text)
                    delivered += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                blocked += 1
            except Exception:
                logger.exception("broadcast failed for %s", user_id)
                failed += 1

        if start + BROADCAST_CHUNK < len(recipients):
            await asyncio.sleep(BROADCAST_CHUNK / BROADCAST_RATE)

    logger.info(
        "broadcast complete: %d delivered, %d blocked, %d failed",
        delivered, blocked, failed,
    )
    return delivered, blocked, failed
