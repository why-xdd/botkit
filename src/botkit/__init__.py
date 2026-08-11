"""botkit — an aiogram 3 starter with the boring parts already solved.

FSM forms that can be cancelled, i18n resolved in middleware, role-based access
control, per-user rate limiting, one database session per update, and a
broadcast that respects Telegram's rate limits.
"""

from .config import Settings
from .filters import ChatType, HasRole, IsAdmin, IsOwner, NotBanned
from .i18n import BoundTranslator, I18nMiddleware, Translator
from .middlewares import (
    DatabaseMiddleware,
    ErrorMiddleware,
    ThrottleMiddleware,
    UserMiddleware,
)
from .storage import Repository, Role, User, create_schema, make_engine, make_session_factory

__version__ = "0.1.0"

__all__ = [
    "BoundTranslator",
    "ChatType",
    "DatabaseMiddleware",
    "ErrorMiddleware",
    "HasRole",
    "I18nMiddleware",
    "IsAdmin",
    "IsOwner",
    "NotBanned",
    "Repository",
    "Role",
    "Settings",
    "ThrottleMiddleware",
    "Translator",
    "User",
    "UserMiddleware",
    "create_schema",
    "make_engine",
    "make_session_factory",
]
