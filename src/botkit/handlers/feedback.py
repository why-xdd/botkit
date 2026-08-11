"""A multi-step form, which is what FSM is actually for.

Three states: category, then message, then confirmation. It demonstrates the
parts every real bot form needs and most examples skip — going back a step,
cancelling from anywhere, validating input without losing what was already
typed, and a confirmation screen before anything is sent.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..filters import NotBanned
from ..i18n import BoundTranslator
from ..keyboards import (
    CATEGORIES,
    cancel_keyboard,
    category_keyboard,
    confirm_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="feedback")
router.message.filter(NotBanned())
router.callback_query.filter(NotBanned())

MIN_LENGTH = 10
MAX_LENGTH = 2000


class Feedback(StatesGroup):
    category = State()
    message = State()
    confirm = State()


@router.message(Command("feedback"))
async def start_feedback(message: Message, state: FSMContext, i18n: BoundTranslator) -> None:
    await state.set_state(Feedback.category)
    await message.answer(
        i18n("feedback.choose_category"), reply_markup=category_keyboard(i18n)
    )


# Registered for any state so cancelling works mid-form. Without this a user who
# starts a form and changes their mind is stuck until the FSM times out, and
# every subsequent message is swallowed as form input.
@router.message(Command("cancel"), StateFilter("*"))
@router.callback_query(F.data == "cancel", StateFilter("*"))
async def cancel(
    event: Message | CallbackQuery, state: FSMContext, i18n: BoundTranslator
) -> None:
    if await state.get_state() is None:
        if isinstance(event, CallbackQuery):
            await event.answer()
        return

    await state.clear()
    text = i18n("feedback.cancelled")
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.edit_text(text)
    else:
        await event.answer(text)


@router.callback_query(Feedback.category, F.data.startswith("category:"))
async def choose_category(
    callback: CallbackQuery, state: FSMContext, i18n: BoundTranslator
) -> None:
    category = callback.data.removeprefix("category:")
    if category not in CATEGORIES:
        # Stale keyboard from an older deploy, or a hand-crafted callback.
        await callback.answer(i18n("feedback.unknown_category"), show_alert=True)
        return

    await state.update_data(category=category)
    await state.set_state(Feedback.message)
    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            i18n("feedback.write_message", category=i18n(f"category.{category}")),
            reply_markup=cancel_keyboard(i18n),
        )


@router.message(Feedback.message, F.text)
async def receive_message(
    message: Message, state: FSMContext, i18n: BoundTranslator
) -> None:
    text = (message.text or "").strip()

    # Validation keeps the state, so a too-short message costs one more line
    # rather than restarting the whole form.
    if len(text) < MIN_LENGTH:
        await message.answer(i18n("feedback.too_short", min=MIN_LENGTH))
        return
    if len(text) > MAX_LENGTH:
        await message.answer(i18n("feedback.too_long", max=MAX_LENGTH))
        return

    await state.update_data(text=text)
    await state.set_state(Feedback.confirm)

    data = await state.get_data()
    await message.answer(
        i18n(
            "feedback.confirm",
            category=i18n(f"category.{data['category']}"),
            text=text,
        ),
        reply_markup=confirm_keyboard(i18n),
    )


@router.message(Feedback.message)
async def reject_non_text(message: Message, i18n: BoundTranslator) -> None:
    """A photo where text was asked for. Say so instead of ignoring it."""
    await message.answer(i18n("feedback.text_only"))


@router.callback_query(Feedback.confirm, F.data == "confirm")
async def submit(
    callback: CallbackQuery, state: FSMContext, i18n: BoundTranslator
) -> None:
    data = await state.get_data()
    await state.clear()

    # Where a real bot would write to a database or forward to a support chat.
    logger.info(
        "feedback from %s [%s]: %s",
        callback.from_user.id,
        data.get("category"),
        data.get("text", "")[:200],
    )

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(i18n("feedback.thanks"))


@router.callback_query(Feedback.confirm, F.data == "edit")
async def back_to_message(
    callback: CallbackQuery, state: FSMContext, i18n: BoundTranslator
) -> None:
    """Step back without losing the category already chosen."""
    await state.set_state(Feedback.message)
    await callback.answer()

    data = await state.get_data()
    if callback.message:
        await callback.message.edit_text(
            i18n(
                "feedback.write_message",
                category=i18n(f"category.{data['category']}"),
            ),
            reply_markup=cancel_keyboard(i18n),
        )
