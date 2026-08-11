"""Inline keyboards.

Built by functions rather than declared as constants because every label is
translated, and a module-level constant would freeze one locale at import time.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .i18n import BoundTranslator

CATEGORIES = ("bug", "idea", "question", "other")


def category_keyboard(i18n: BoundTranslator) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in CATEGORIES:
        builder.button(
            text=i18n(f"category.{category}"), callback_data=f"category:{category}"
        )
    builder.button(text=i18n("button.cancel"), callback_data="cancel")
    # Two columns for the categories, then the cancel button alone on its own
    # row — a destructive action sitting beside a normal one gets misclicked.
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def confirm_keyboard(i18n: BoundTranslator) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=i18n("button.send"), callback_data="confirm")
    builder.button(text=i18n("button.edit"), callback_data="edit")
    builder.button(text=i18n("button.cancel"), callback_data="cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def cancel_keyboard(i18n: BoundTranslator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n("button.cancel"), callback_data="cancel")]
        ]
    )


def language_keyboard(locales: list[str], current: str) -> InlineKeyboardMarkup:
    """Language names in their own language, never translated.

    A user looking for their language scans for a word they recognise. Showing
    "Russian" to someone who only reads Russian defeats the entire screen.
    """
    names = {
        "en": "English",
        "ru": "Русский",
        "es": "Español",
        "de": "Deutsch",
        "fr": "Français",
    }

    builder = InlineKeyboardBuilder()
    for locale in locales:
        label = names.get(locale, locale.upper())
        if locale == current:
            label = f"✓ {label}"
        builder.button(text=label, callback_data=f"lang:{locale}")
    builder.adjust(2)
    return builder.as_markup()


def admin_keyboard(i18n: BoundTranslator) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=i18n("admin.button.stats"), callback_data="admin:stats")
    builder.button(text=i18n("admin.button.broadcast"), callback_data="admin:broadcast")
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_keyboard(i18n: BoundTranslator, count: int) -> InlineKeyboardMarkup:
    """Confirmation for a broadcast, with the recipient count on the button.

    Putting the number on the button itself is the point: "Send" is easy to
    click reflexively, "Send to 12 480 people" is not.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=i18n("admin.button.confirm_broadcast", count=count),
        callback_data="broadcast:confirm",
    )
    builder.button(text=i18n("button.cancel"), callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()
