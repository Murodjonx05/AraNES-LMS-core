from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.startup.bootstrap import run_startup_alembic_upgrade


def test_run_startup_alembic_upgrade_rejects_in_memory_sqlite():
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            BASE_DIR=Path("/tmp/app"),
        )
    )

    with patch("src.startup.bootstrap.command.upgrade") as upgrade_mock:
        with pytest.raises(RuntimeError, match="in-memory SQLite"):
            run_startup_alembic_upgrade(runtime=runtime)  # type: ignore[arg-type]

    upgrade_mock.assert_not_called()
