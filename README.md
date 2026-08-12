<div align="center">

# botkit

**An aiogram 3 starter where the boring parts are already correct.**
FSM forms you can actually cancel, i18n resolved in middleware, role-based access, per-user rate limiting, and a broadcast that will not get you rate-limited.

[![CI](https://github.com/why-xdd/botkit/actions/workflows/ci.yml/badge.svg)](https://github.com/why-xdd/botkit/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3-2CA5E0?logo=telegram&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

<img width="580" src="https://raw.githubusercontent.com/why-xdd/botkit/main/docs/banner.svg" alt="botkit — an aiogram 3 starter with FSM, i18n, roles and a paced broadcast"/>

</div>

---

Every Telegram bot tutorial gets you to "echo bot" and stops. Everything after
that — the second language, the first admin, the form a user abandons halfway,
the broadcast that hits Telegram's rate limit at user 400 — you rebuild from
scratch, slightly wrong, every time.

botkit is those parts, written once with the reasoning left in the code.

```bash
git clone https://github.com/why-xdd/botkit && cd botkit
cp .env.example .env          # add your token from @BotFather
pip install -e ".[dev,redis]"
alembic upgrade head
botkit
```

---

## What is actually in here

### Middleware order, which is load-bearing

```
ErrorMiddleware        ← outermost: sees every failure below it
  DatabaseMiddleware   ← one session per update, committed only on success
    UserMiddleware     ← upserts the user, resolves their role
      I18nMiddleware   ← binds the translator to their language
        ThrottleMiddleware   ← innermost
          handler
```

Putting the throttle first is the intuitive choice and breaks three things at
once: a rate-limited user would not be recorded, would have no role (so admins
could not be exempted), and would get the warning in the wrong language.

The database layer commits only if the handler returned. A handler that raises
halfway leaves nothing half-written.

### A form that can be abandoned

`/feedback` is a three-state FSM — category → message → confirm — and it covers
what real forms need and examples skip:

- **`/cancel` works from any state.** Without a `StateFilter("*")` handler, a
  user who starts a form and changes their mind is stuck until the FSM times
  out, and every message they send is silently eaten as form input.
- **Validation keeps the state.** A too-short message costs one more line, not
  the whole form.
- **Going back preserves what was already entered.**
- **`/start` clears state**, because that is what people press when they are
  lost.

<img src="https://raw.githubusercontent.com/why-xdd/botkit/main/docs/conversation.png" alt="The feedback flow: category buttons, the message prompt, a confirmation screen, and the thank-you" width="560"/>

*Rendered from `locales/en.json` — the strings are the ones the bot sends,
read from the catalogue rather than retyped.*

### i18n that fails visibly

A missing key renders as `⟨settings.title⟩`, never as a blank string. A blank
button is undebuggable from a screenshot; a visible key tells you exactly what
to add.

Regional codes fall back to the base language, so `pt-BR` finds your Portuguese
catalogue instead of dropping to English. A user's explicit choice beats
Telegram's `language_code` forever after — switching your phone to another
language should not undo a decision you made in the bot.

**CI fails the build if a locale is missing a key, or if a translation renamed a
placeholder** (`{count}` → `{число}` would otherwise raise at runtime, in
production, for the users whose language you do not read).

### Roles that compare, not enumerate

```python
@router.message(Command("stats"), HasRole(Role.ADMIN))
```

`Role` is ordered — `OWNER > ADMIN > USER > BANNED` — so `HasRole(Role.ADMIN)`
admits owners without anyone having to remember to list them. Writing
`role == Role.ADMIN` is how an owner gets locked out of their own feature.

Permissions are **filters**, so an unauthorised update never reaches the handler
body. There is no path where the work happens before someone remembers to check.

**Owners come from configuration, not the database.** A bad restore or a stray
`UPDATE` must never be able to lock you out of your own bot, which is also why
`/promote` refuses to grant `owner`.

### A broadcast that behaves

```
Done.

Delivered: 12309
Blocked the bot: 168
Failed: 3
```

- Paced at 25 messages/second, under Telegram's ~30/s ceiling, leaving headroom
  for the traffic the bot is still serving.
- `TelegramRetryAfter` carries the exact backoff — it sleeps that long and
  retries once, instead of dropping the message.
- **Blocked and failed are counted separately.** Users who removed the bot are
  normal attrition; `failed` is the number that should make someone open the
  logs. Collapsing them hides real errors inside expected churn.
- The confirmation button reads *"Send to 12 480 people"*. "Send" is easy to
  click reflexively; a number is not.

### Rate limiting on a sliding window

A fixed window lets a user send the full allowance at t=0.99 and again at
t=1.01 — double the intended rate, at exactly the moment they are hammering the
bot. The window here slides, and there is a test that pins it.

Admins are exempt: the person cleaning up an incident should not be throttled by
the tool they are cleaning it up with. The throttle warns **once per burst**,
otherwise a rate limit becomes a way to make the bot spam the user.

---

## Layout

```
src/botkit/
├── bot.py            # dispatcher wiring, middleware order, startup/shutdown
├── config.py         # env settings, validated at boot
├── storage.py        # SQLAlchemy models + Repository
├── middlewares.py    # session, user, throttle, errors
├── filters.py        # HasRole, NotBanned, ChatType
├── i18n.py           # translator + locale middleware
├── keyboards.py      # inline keyboards, built per-locale
└── handlers/
    ├── common.py     # /start, /help, /language
    ├── feedback.py   # the FSM form
    └── admin.py      # /stats, /broadcast, /promote
locales/{en,ru}.json
migrations/           # Alembic, wired to the same URL the bot uses
```

---

## Configuration

Every setting is a `BOT_`-prefixed environment variable, validated at startup —
a malformed owner list should fail the deploy, not surface the first time
someone runs `/promote`.

| variable | default | notes |
|---|---|---|
| `BOT_TOKEN` | — | Required. Checked for the `<digits>:<secret>` shape. |
| `BOT_OWNER_IDS` | empty | Comma-separated. Config beats the database, always. |
| `BOT_DATABASE_URL` | `sqlite+aiosqlite:///botkit.db` | `postgresql+asyncpg://…` in production |
| `BOT_REDIS_URL` | none | Without it, FSM state dies on restart |
| `BOT_DEFAULT_LOCALE` | `en` | |
| `BOT_THROTTLE_LIMIT` | `5` | messages per window |
| `BOT_THROTTLE_WINDOW` | `2.0` | seconds |

The token is a `SecretStr`, so it cannot leak through an accidental `repr()` of
the settings object into a log line.

---

## Migrations

`create_schema()` exists for tests and the first run. Real deployments use
Alembic — `create_all` cannot alter an existing table, and the second schema
change is where a project that relied on it gets stuck.

```bash
alembic revision --autogenerate -m "add subscriptions"
alembic upgrade head
```

Two details the generated setup gets wrong by default and this one does not:
`render_as_batch` is on for SQLite (which cannot `ALTER` most columns in place),
and the role column is a `VARCHAR` + `CHECK` rather than a native Postgres
`ENUM`, because `ALTER TYPE … ADD VALUE` cannot run inside a transaction on
older versions — a migration that fails halfway is worse than a wider column.

---

## Adding a language

Drop `locales/es.json` in beside the others. It is picked up at startup, appears
in `/language`, and CI immediately tells you which keys are missing.

## Adding a handler

```python
# src/botkit/handlers/mine.py
from aiogram import Router
from aiogram.filters import Command

from ..filters import NotBanned
from ..i18n import BoundTranslator

router = Router(name="mine")
router.message.filter(NotBanned())

@router.message(Command("mine"))
async def mine(message: Message, i18n: BoundTranslator, repo: Repository) -> None:
    await message.answer(i18n("mine.hello"))
```

Register it in `bot.py`. `i18n`, `repo`, `session`, `user` and `role` arrive as
arguments — the middlewares put them there.

---

## Tests

```bash
pytest        # 24 tests
ruff check .
```

No Telegram connection required. The suite covers the things that break quietly
in production rather than loudly in development:

- **An upsert must not demote an admin.** It runs on *every* update, so a naive
  implementation revokes admin rights on the admin's next message — a bug that
  only appears after someone is promoted, long after review.
- **An upsert must not overwrite a chosen locale**, since Telegram keeps sending
  the phone's `language_code`.
- **Telegram IDs exceed 2³¹.** SQLite shrugs; Postgres rejects the row, in
  production only.
- **The sliding window must not let double the rate through a boundary.**
- **Every locale must have identical keys and identical placeholders.**
- **Filters must fail closed** when no role is present.

---

## Docker

```bash
docker compose up --build      # bot + Postgres + Redis
```

MIT © [why-xdd](https://github.com/why-xdd)
