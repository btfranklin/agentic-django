from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_tag_draft_waits_for_complete_reusable_validation() -> None:
    draft = workflow("create-draft-release.yml")
    verification = workflow("verify-release.yml")
    ci = workflow("python-package.yml")

    assert 'tags:\n            - "v*.*.*"' in draft
    assert "uses: ./.github/workflows/verify-release.yml" in draft
    assert "draft-release:\n        needs: verify-release" in draft
    assert "uses: btfranklin/release-notes-scribe@v0" in draft
    assert 'draft: "true"' in draft
    assert 'create_release: "true"' in draft
    assert "workflow_call:" in verification
    assert "uses: ./.github/workflows/python-package.yml" in verification
    assert "package-verification:\n        needs: validation" in verification
    assert "run: pdm build" in verification
    assert "run: pdm run package-check" in verification
    assert "workflow_call:" in ci
    assert 'python-version: ["3.12", "3.13", "3.14"]' in ci
    for command in (
        "pdm install --group dev --group rq",
        "pdm run lint",
        "pdm run typecheck",
        "pdm run pytest",
        "perfect-doc check --offline --no-banner",
    ):
        assert command in ci


def test_published_release_builds_tag_and_uses_trusted_publishing() -> None:
    publisher = workflow("python-publish.yml")

    assert "release:\n        types: [published]" in publisher
    assert "uses: actions/checkout@v7" in publisher
    assert "fetch-depth: 0" in publisher
    assert "ref: ${{ github.event.release.tag_name }}" in publisher
    assert "uses: actions/setup-python@v7" in publisher
    assert "uses: pdm-project/setup-pdm@v4" in publisher
    assert "environment: release" in publisher
    assert "id-token: write" in publisher
    assert "uses: pypa/gh-action-pypi-publish@release/v1" in publisher
    # Keep publication limited to building and publishing, with no second suite
    # hidden behind a reusable workflow or an archive download from another run.
    assert re.findall(r"^\s+run: (.+)$", publisher, re.MULTILINE) == ["pdm build"]
    actions = re.findall(r"uses: (.+)", publisher)
    assert actions == [
        "actions/checkout@v7",
        "actions/setup-python@v7",
        "pdm-project/setup-pdm@v4",
        "pypa/gh-action-pypi-publish@release/v1",
    ]


def test_build_does_not_trigger_validation_hooks() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = config["tool"]["pdm"]["scripts"]

    assert "pre_build" not in scripts
    assert "post_build" not in scripts
    assert "custom-hook" not in config["tool"]["pdm"]["build"]
    assert not (ROOT / "pdm_build.py").exists()
