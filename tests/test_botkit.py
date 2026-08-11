from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from botkit.filters import ChatType, HasRole, NotBanned
from botkit.i18n import Translator
from botkit.middlewares import ThrottleMiddleware
from botkit.storage import (
    Repository,
    Role,
    create_schema,
    make_engine,
    make_session_factory,
)

LOCALES = Path(__file__).resolve().parents[1] / "locales"


# -- roles ------------------------------------------------------------------


def test_roles_are_ordered():
    assert Role.OWNER.rank > Role.ADMIN.rank > Role.USER.rank > Role.BANNED.rank


def test_owner_satisfies_an_admin_requirement():
    """The reason permissions compare by rank instead of listing roles.

    Enumerating allowed roles is how an owner ends up locked out of a feature
    because someone wrote `role == Role.ADMIN`.
    """
    assert Role.OWNER.can_act_as(Role.ADMIN)
    assert Role.ADMIN.can_act_as(Role.ADMIN)
    assert not Role.USER.can_act_as(Role.ADMIN)
    assert not Role.BANNED.can_act_as(Role.USER)


@pytest.mark.asyncio
async def test_has_role_filter():
    admin_only = HasRole(Role.ADMIN)
    assert await admin_only(None, role=Role.OWNER)
    assert await admin_only(None, role=Role.ADMIN)
    assert not await admin_only(None, role=Role.USER)
    # No role in the data at all — an update that skipped the user middleware
    # must fail closed, not open.
    assert not await admin_only(None, role=None)


@pytest.mark.asyncio
async def test_not_banned_filter():
    assert await NotBanned()(None, role=Role.USER)
    assert not await NotBanned()(None, role=Role.BANNED)


def test_chat_type_requires_at_least_one_type():
    with pytest.raises(ValueError):
        ChatType()


# -- storage ----------------------------------------------------------------


@pytest_asyncio.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_schema(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        yield Repository(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_creates_then_updates(repo):
    created = await repo.upsert(1, username="alice", full_name="Alice")
    assert created.role is Role.USER

    updated = await repo.upsert(1, username="alice2", full_name="Alice B")
    assert updated.username == "alice2"
    assert await repo.count() == 1


@pytest.mark.asyncio
async def test_upsert_does_not_demote_an_admin(repo):
    """Regression risk: upsert runs on *every* update.

    If it reset the role, an admin would lose their rights on their next message
    — a bug that only appears after someone is promoted, which is well after the
    code was reviewed.
    """
    await repo.upsert(1, username="alice")
    await repo.set_role(1, Role.ADMIN)

    refreshed = await repo.upsert(1, username="alice")
    assert refreshed.role is Role.ADMIN


@pytest.mark.asyncio
async def test_upsert_preserves_a_chosen_locale(repo):
    await repo.upsert(1, locale="en")
    await repo.set_locale(1, "ru")

    # Telegram keeps sending language_code=en; the user's explicit choice wins.
    refreshed = await repo.upsert(1, locale="en")
    assert refreshed.locale == "ru"


@pytest.mark.asyncio
async def test_broadcast_recipients_exclude_banned_users(repo):
    for user_id in (1, 2, 3):
        await repo.upsert(user_id)
    await repo.set_role(3, Role.BANNED)

    assert sorted(await repo.recipients()) == [1, 2]


@pytest.mark.asyncio
async def test_count_by_role(repo):
    for user_id in (1, 2, 3):
        await repo.upsert(user_id)
    await repo.set_role(2, Role.ADMIN)

    counts = await repo.count_by_role()
    assert counts[Role.USER] == 2
    assert counts[Role.ADMIN] == 1


@pytest.mark.asyncio
async def test_set_role_on_an_unknown_user_returns_none(repo):
    assert await repo.set_role(999, Role.ADMIN) is None


@pytest.mark.asyncio
async def test_telegram_ids_exceed_32_bits(repo):
    """Telegram user IDs are past 2^31. BigInteger is not optional."""
    big = 7_123_456_789
    await repo.upsert(big, username="new")
    assert (await repo.get(big)).id == big


# -- i18n -------------------------------------------------------------------


@pytest.fixture
def translator() -> Translator:
    return Translator.from_directory(LOCALES, default="en")


def test_every_locale_has_the_same_keys(translator):
    """A missing key ships as ⟨key⟩ to real users, so catch it in CI instead."""
    reference = set(translator.catalogues["en"])
    for locale, catalogue in translator.catalogues.items():
        missing = reference - set(catalogue)
        extra = set(catalogue) - reference
        assert not missing, f"{locale} is missing: {sorted(missing)}"
        assert not extra, f"{locale} has keys en does not: {sorted(extra)}"


def test_placeholders_match_across_locales(translator):
    """A translation that renamed {count} to {число} would raise at runtime."""
    import re

    fields = lambda text: set(re.findall(r"\{(\w+)\}", text))  # noqa: E731

    for key, english in translator.catalogues["en"].items():
        expected = fields(english)
        for locale, catalogue in translator.catalogues.items():
            if key in catalogue:
                assert fields(catalogue[key]) == expected, (
                    f"{locale}:{key} placeholders differ from en"
                )


def test_regional_codes_fall_back_to_the_base_language(translator):
    assert translator.resolve("ru-RU") == "ru"
    assert translator.resolve("en-GB") == "en"
    assert translator.resolve("zz") == "en"
    assert translator.resolve(None) == "en"


def test_missing_key_is_visible_not_blank(translator):
    """A blank button is undebuggable from a screenshot; a key is not."""
    assert translator.get("no.such.key", "en") == "⟨no.such.key⟩"


def test_missing_translation_falls_back_to_the_default_locale():
    translator = Translator({"en": {"a": "A", "b": "B"}, "ru": {"a": "RU-A"}})
    assert translator.get("b", "ru") == "B"


def test_formatting_error_returns_text_rather_than_raising():
    """A translator typo must not take down the handler."""
    translator = Translator({"en": {"greet": "Hi {name}"}})
    assert translator.get("greet", "en") == "Hi {name}"
    assert translator.get("greet", "en", name="Bob") == "Hi Bob"


def test_bound_translator_is_callable(translator):
    i18n = translator.bind("ru")
    assert i18n.locale == "ru"
    assert i18n("button.cancel") == "Отмена"


def test_default_locale_must_exist():
    with pytest.raises(ValueError):
        Translator({"ru": {}}, default="en")


def test_locale_files_are_valid_json():
    for path in LOCALES.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


# -- throttling -------------------------------------------------------------


def test_throttle_allows_up_to_the_limit():
    throttle = ThrottleMiddleware(limit=3, window=10)
    assert [throttle.allow(1, now=0) for _ in range(3)] == [True, True, True]
    assert throttle.allow(1, now=0) is False


def test_throttle_window_slides():
    """A fixed window lets a user send double the rate across a boundary.

    Five at t=0.99 and five at t=1.01 is ten in 20 ms under fixed buckets — at
    exactly the moment someone is hammering the bot.
    """
    throttle = ThrottleMiddleware(limit=2, window=1.0)

    assert throttle.allow(1, now=0.0)
    assert throttle.allow(1, now=0.99)
    assert not throttle.allow(1, now=1.0), "still two events inside the window"

    # Only once the first event ages out does a slot free up.
    assert throttle.allow(1, now=1.5)


def test_throttle_is_per_user():
    throttle = ThrottleMiddleware(limit=1, window=10)
    assert throttle.allow(1, now=0)
    assert not throttle.allow(1, now=0)
    assert throttle.allow(2, now=0), "one user must not throttle another"
