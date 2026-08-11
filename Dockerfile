FROM python:3.12-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps -w /wheels .


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl "redis>=5.0" "asyncpg>=0.29" \
    && rm -rf /wheels

COPY locales ./locales
COPY migrations ./migrations
COPY alembic.ini ./

# Not root: a bot process that is compromised should not own the filesystem.
RUN useradd --create-home --uid 10001 bot
USER bot

CMD ["botkit"]
