"""Permission filters.

A filter rather than a check inside the handler: an unauthorised update never
reaches the handler body, so there is no path where the work happens before
someone remembers to verify the caller.
"""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, TelegramObject

from .storage import Role


class HasRole(Filter):
    """Passes when the caller's role is at least ``required``.

    Compares by rank, so ``HasRole(Role.ADMIN)`` admits owners without anyone
    having to remember to list them. Forgetting to include the higher role is
    the classic way these checks break.
    """

    def __init__(self, required: Role) -> None:
        self.required = required

    async def __call__(self, event: TelegramObject, role: Role | None = None) -> bool:
        return role is not None and role.can_act_as(self.required)


class IsAdmin(HasRole):
    def __init__(self) -> None:
        super().__init__(Role.ADMIN)


class IsOwner(HasRole):
    def __init__(self) -> None:
        super().__init__(Role.OWNER)


class NotBanned(Filter):
    """Blocks banned users everywhere, silently.

    Silence is the point. Telling someone they are banned invites them to argue
    about it, or to work out which account is not banned yet.
    """

    async def __call__(self, event: TelegramObject, role: Role | None = None) -> bool:
        return role != Role.BANNED


class ChatType(Filter):
    """Restricts a handler to private chats, groups, or channels."""

    def __init__(self, *types: str) -> None:
        if not types:
            raise ValueError("at least one chat type is required")
        self.types = frozenset(types)

    async def __call__(self, event: TelegramObject) -> bool:
        if isinstance(event, Message):
            return event.chat.type in self.types
        if isinstance(event, CallbackQuery) and event.message is not None:
            return event.message.chat.type in self.types
        return False
