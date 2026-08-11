"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        # BigInteger, not Integer: Telegram user IDs passed 2^31 years ago.
        # SQLite would not complain; Postgres would, in production only.
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("locale", sa.String(8), nullable=True),
        # native_enum=False stores the role as a VARCHAR with a CHECK constraint.
        # A native Postgres ENUM needs ALTER TYPE to add a value, which cannot
        # run inside a transaction on older versions — a migration that fails
        # halfway is a worse trade than a slightly wider column.
        sa.Column(
            "role",
            sa.Enum("banned", "user", "admin", "owner", name="role", native_enum=False),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Admin listings and broadcast recipient queries both filter on role.
    op.create_index("ix_users_role", "users", ["role"])


def downgrade() -> None:
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
