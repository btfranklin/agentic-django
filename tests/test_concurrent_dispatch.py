from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("shared_session", [False, True])
@pytest.mark.parametrize("existing_lock", [False, True])
def test_workers_reserve_slots_without_sqlite_lock_errors(
    tmp_path: Path, shared_session: bool, existing_lock: bool,
) -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "tests.scenarios.concurrent_dispatch",
            str(tmp_path / "dispatch.sqlite3"),
            str(int(shared_session)), str(int(existing_lock)),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
