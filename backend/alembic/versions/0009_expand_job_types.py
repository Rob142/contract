"""Expand freelance job categories without changing existing records."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLES = ("users", "contracts", "projects", "analysis_jobs", "portfolio_items")
JOBS = (
    "'dev', 'design', 'video', 'marketing', 'writing', 'translation', "
    "'education', 'consulting', 'photography', 'other'"
)


def upgrade() -> None:
    for table in TABLES:
        op.drop_constraint(f"{table}_job_type_check", table, type_="check")
        op.create_check_constraint(f"{table}_job_type_check", table, f"job_type IN ({JOBS})")


def downgrade() -> None:
    # Refuse to erase or silently reclassify users of the new categories.
    for table in TABLES:
        op.drop_constraint(f"{table}_job_type_check", table, type_="check")
        op.create_check_constraint(
            f"{table}_job_type_check", table, "job_type IN ('dev', 'design', 'video', 'marketing')"
        )
