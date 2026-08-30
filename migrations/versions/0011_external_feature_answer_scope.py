"""Separate verified external-feature history from Mory FAQ optimization.

Revision ID: 0011_external_feature_answer_scope
Revises: 0010_question_answer_provenance
Create Date: 2026-08-31

Only exact phrases confirmed in the production read-only audit are backfilled.
Owner-authored configured questions such as ``积分有什么用`` are intentionally
untouched.  Downgrade preserves the evidence instead of erasing provenance.
"""

import time

import sqlalchemy as sa
from alembic import op


revision = "0011_external_feature_answer_scope"
down_revision = "0010_question_answer_provenance"
branch_labels = None
depends_on = None


_VERIFIED_EXTERNAL_TEXTS = (
    "签到！！！",
    "什么？我断签了🤪",
    "多少积分兑换",
    "现在不可以用积分兑换了吗",
    "签到积分能干嘛",
    "签到签到",
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("user_questions"):
        columns = {item["name"] for item in inspector.get_columns("user_questions")}
        if {"question_text", "answer_source", "answer_ref"} <= columns:
            for text in _VERIFIED_EXTERNAL_TEXTS:
                bind.execute(
                    sa.text(
                        """UPDATE user_questions
                           SET answer_source='delegated', answer_ref='other_bot_feature'
                           WHERE question_text=:text
                             AND COALESCE(answer_source, '')=''"""
                    ),
                    {"text": text},
                )

    if inspector.has_table("faq_candidates"):
        columns = {item["name"] for item in inspector.get_columns("faq_candidates")}
        required = {"question_pattern", "status", "reviewed_by", "reviewed_at"}
        if required <= columns:
            bind.execute(
                sa.text(
                    """UPDATE faq_candidates
                       SET status='rejected', reviewed_by='scope_cleanup_v5.42.3',
                           reviewed_at=:reviewed_at
                       WHERE question_pattern='签到' AND status='pending'"""
                ),
                {"reviewed_at": int(time.time())},
            )


def downgrade():
    """Keep provenance and review evidence across code rollback."""
