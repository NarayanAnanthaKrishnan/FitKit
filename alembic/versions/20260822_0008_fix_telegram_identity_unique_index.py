"""Align telegram_identities uniqueness with the model metadata.

The model declares ``telegram_user_id`` as ``unique=True, index=True``
(a single unique index). The initial migration created a separate unnamed
UNIQUE constraint plus a non-unique index instead, which fails
``alembic check`` on databases built purely from migrations.

Revision ID: 20260822_0008
Revises: 20260822_0007
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260822_0008"
down_revision: Union[str, None] = "20260822_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Auto-generated name for the unnamed UniqueConstraint in revision 0001.
    op.drop_constraint(
        "telegram_identities_telegram_user_id_key",
        "telegram_identities",
        type_="unique",
    )
    op.drop_index(
        "ix_telegram_identities_telegram_user_id", table_name="telegram_identities"
    )
    op.create_index(
        "ix_telegram_identities_telegram_user_id",
        "telegram_identities",
        ["telegram_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_identities_telegram_user_id", table_name="telegram_identities"
    )
    op.create_index(
        "ix_telegram_identities_telegram_user_id",
        "telegram_identities",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "telegram_identities_telegram_user_id_key",
        "telegram_identities",
        ["telegram_user_id"],
    )
