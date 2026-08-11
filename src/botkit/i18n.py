"""Translations, and the middleware that picks one per update.

Two decisions shape this module.

*Fall back to a key, never to a blank.* A missing translation renders as
``⟨settings.title⟩`` rather than an empty string or a crash. A blank button is
undebuggable in a screenshot; a visible key tells you exactly what to add.

*Resolve the locale once, in middleware.* Handlers receive the translator
already bound to the user's language. Doing the lookup inside each handler means
one of them eventually forgets, and that bug reaches only the users whose
language you do not speak.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

DEFAULT_LOCALE = "en"


class Translator:
    """Message catalogues, one dict per locale."""

    def __init__(self, catalogues: dict[str, dict[str, str]], default: str = DEFAULT_LOCALE):
        if default not in catalogues:
            raise ValueError(f"no catalogue for the default locale {default!r}")
        self.catalogues = catalogues
        self.default = default

    @classmethod
    def from_directory(cls, directory: Path, default: str = DEFAULT_LOCALE) -> Translator:
        """Load every ``<locale>.json`` in a directory."""
        catalogues: dict[str, dict[str, str]] = {}
        for path in sorted(Path(directory).glob("*.json")):
            catalogues[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        if not catalogues:
            raise ValueError(f"no locale files found in {directory}")
        return cls(catalogues, default)

    @property
    def locales(self) -> list[str]:
        return sorted(self.catalogues)

    def resolve(self, locale: str | None) -> str:
        """Map a Telegram language code onto a catalogue we actually have.

        Telegram sends codes like ``pt-BR`` and ``en-GB``. Matching the base
        language means a Brazilian user gets Portuguese instead of English,
        which is almost always what they wanted.
        """
        if not locale:
            return self.default
        if locale in self.catalogues:
            return locale
        base = locale.split("-")[0]
        return base if base in self.catalogues else self.default

    def get(self, key: str, locale: str | None = None, /, **params: Any) -> str:
        """Translate ``key``, formatting any ``{placeholders}``."""
        resolved = self.resolve(locale)
        text = self.catalogues[resolved].get(key)

        if text is None and resolved != self.default:
            text = self.catalogues[self.default].get(key)
        if text is None:
            return f"⟨{key}⟩"

        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError):
            # A translator typo in one locale must not take the bot down. The
            # unformatted string is still readable; a KeyError mid-handler is not.
            return text

    def bind(self, locale: str | None) -> BoundTranslator:
        return BoundTranslator(self, self.resolve(locale))


class BoundTranslator:
    """A translator with the locale already decided. Handlers get one of these."""

    __slots__ = ("_translator", "locale")

    def __init__(self, translator: Translator, locale: str) -> None:
        self._translator = translator
        self.locale = locale

    def __call__(self, key: str, /, **params: Any) -> str:
        return self._translator.get(key, self.locale, **params)

    get = __call__


class I18nMiddleware(BaseMiddleware):
    """Injects ``i18n`` into every handler, using the user's stored preference.

    ``locale_getter`` lets a stored preference win over Telegram's own
    ``language_code``: a user who explicitly picked English in the bot should
    keep it after switching their phone to another language.
    """

    def __init__(
        self,
        translator: Translator,
        locale_getter: Callable[[int], Awaitable[str | None]] | None = None,
    ) -> None:
        self.translator = translator
        self.locale_getter = locale_getter

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        locale = user.language_code if user else None

        if user is not None and self.locale_getter is not None:
            stored = await self.locale_getter(user.id)
            if stored:
                locale = stored

        data["i18n"] = self.translator.bind(locale)
        return await handler(event, data)
