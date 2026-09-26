from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec('django_tasks_rq') is None,
    reason='Install the rq extra to test the RQ backend.',
)
def test_rq_configuration_loads_and_submits_the_package_task() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.scenarios.rq_backend"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
