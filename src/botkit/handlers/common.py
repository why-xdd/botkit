"""Start, help, and language selection."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..filters import NotBanned
from ..i18n import BoundTranslator, Translator
from ..keyboards import language_keyboard
from ..storage import Repository, Role

router = Router(name="common")
router.message.filter(NotBanned())
router.callback_query.filter(NotBanned())


@router.message(CommandStart())
async def start(
    message: Message, state: FSMContext, i18n: BoundTranslator, role: Role
) -> None:
    # /start is what people press when they are lost, including out of a broken
    # form. Clearing state makes it a reliable escape hatch.
    await state.clear()

    text = i18n("start", name=message.from_user.full_name)
    if role.can_act_as(Role.ADMIN):
        text += "\n\n" + i18n("start.admin_hint")

    await message.answer(text)


@router.message(Command("help"))
async def help_command(message: Message, i18n: BoundTranslator, role: Role) -> None:
    text = i18n("help")
    if role.can_act_as(Role.ADMIN):
        text += "\n\n" + i18n("help.admin")
    await message.answer(text)


@router.message(Command("language"))
async def choose_language(
    message: Message, i18n: BoundTranslator, translator: Translator
) -> None:
    await message.answer(
        i18n("language.choose"),
        reply_markup=language_keyboard(translator.locales, i18n.locale),
    )


@router.callback_query(F.data.startswith("lang:"))
async def set_language(
    callback: CallbackQuery,
    repo: Repository,
    translator: Translator,
    i18n: BoundTranslator,
) -> None:
    locale = callback.data.removeprefix("lang:")
    if locale not in translator.catalogues:
        await callback.answer(i18n("language.unknown"), show_alert=True)
        return

    await repo.set_locale(callback.from_user.id, locale)

    # The middleware bound i18n before this handler ran, so it still holds the
    # *old* locale. Rebinding here is what makes the confirmation appear in the
    # language just chosen rather than the one being left.
    updated = translator.bind(locale)
    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            updated("language.set"),
            reply_markup=language_keyboard(translator.locales, locale),
        )
