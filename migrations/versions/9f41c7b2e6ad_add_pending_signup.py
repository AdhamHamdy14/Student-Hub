"""add pending signup verification

Revision ID: 9f41c7b2e6ad
Revises: 7fdc3f3df345
Create Date: 2026-11-22 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9f41c7b2e6ad"
down_revision = "7fdc3f3df345"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pending_signup",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=False),
        sa.Column("student_id", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("student_id"),
    )


def downgrade():
    op.drop_table("pending_signup")
