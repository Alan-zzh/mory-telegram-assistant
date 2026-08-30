"""Track the provenance of every recorded question answer.

Revision ID: 0010_question_answer_provenance
Revises: 0009_centralize_runtime_schema
Create Date: 2026-08-31

Older rows deliberately keep an empty source because their real reply path
cannot be reconstructed reliably.  The columns are retained on downgrade so a
code rollback cannot erase conversation evidence; older code safely ignores
the additive fields.
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_question_answer_provenance"
down_revision = "0009_centralize_runtime_schema"
branch_labels = None
depends_on = None


def _add_column_if_missing(bind, table_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade():
    bind = op.get_bind()
    _add_column_if_missing(
        bind,
        "user_questions",
        sa.Column("answer_source", sa.Text(), nullable=False, server_default=""),
    )
    _add_column_if_missing(
        bind,
        "user_questions",
        sa.Column("answer_ref", sa.Text(), nullable=False, server_default=""),
    )


def downgrade():
    """Keep additive observability fields so rollback cannot delete evidence."""
