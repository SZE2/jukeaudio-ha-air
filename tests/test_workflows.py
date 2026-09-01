"""Regression checks for repository validation workflow triggers."""

from __future__ import annotations

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("workflow", ("hassfest.yml", "hacs.yml"))
def test_validation_workflow_runs_on_main_changes_without_daily_schedule(
    workflow: str,
) -> None:
    """Validation is event-driven and does not generate daily maintenance mail."""
    source = (REPOSITORY_ROOT / ".github" / "workflows" / workflow).read_text(
        encoding="utf-8"
    )

    assert "schedule:" not in source
    assert "push:\n    branches: [main]" in source
    assert "pull_request:" in source
