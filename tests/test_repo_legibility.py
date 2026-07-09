from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_agents_md_stays_short_and_routes_to_current_truth() -> None:
    agents = read_text("AGENTS.md")

    assert len(agents.splitlines()) <= 80, (
        "Keep AGENTS.md as a short routing map; move durable guidance into docs/."
    )
    for path in (
        "README.md",
        "docs/architecture.md",
        "docs/quality.md",
        "docs/releasing.md",
        "docs/skills.md",
        "AGENTIC_DJANGO_DESIGN.md",
        "skills/agentic-django-integration/SKILL.md",
    ):
        assert path in agents, f"AGENTS.md must route future agents to {path}."


def test_docs_index_links_core_legibility_artifacts() -> None:
    index = read_text("docs/index.md")

    for path in (
        "docs/architecture.md",
        "docs/quality.md",
        "docs/releasing.md",
        "docs/skills.md",
        "AGENTS.md",
        "AGENTIC_DJANGO_DESIGN.md",
    ):
        assert path in index, f"docs/index.md must link to {path}."


def test_design_doc_is_marked_as_historical() -> None:
    design_doc = read_text("AGENTIC_DJANGO_DESIGN.md").lower()

    assert "historical design record" in design_doc
    assert "docs/architecture.md" in design_doc
    assert "docs/quality.md" in design_doc


def test_release_guidance_captures_tag_first_release_notes_flow() -> None:
    release_guidance = read_text("docs/releasing.md")

    required_fragments = [
        "release-notes-scribe",
        "Draft Release Notes",
        "git tag",
        "git push origin",
        ".github/workflows/draft-release-notes.yml",
        ".github/workflows/python-publish.yml",
        "PyPI",
    ]
    missing_fragments = [
        fragment for fragment in required_fragments if fragment not in release_guidance
    ]

    assert not missing_fragments, (
        "Release guidance must preserve the tag-first release notes process. "
        f"Missing: {missing_fragments}"
    )


def test_pyproject_exposes_canonical_validation_scripts() -> None:
    config = tomllib.loads(read_text("pyproject.toml"))
    scripts = config["tool"]["pdm"]["scripts"]

    assert scripts["lint"] == "ruff check src tests"
    assert scripts["test"] == "pytest"
    assert scripts["check"]["composite"] == ["lint", "test"]


def test_low_level_modules_do_not_import_orchestration_layers() -> None:
    forbidden_imports = {
        "src/agentic_django/models.py": {
            "agentic_django.registry",
            "agentic_django.serializers",
            "agentic_django.services",
            "agentic_django.tasks",
            "agentic_django.views",
        },
        "src/agentic_django/serializers.py": {
            "agentic_django.models",
            "agentic_django.registry",
            "agentic_django.services",
            "agentic_django.tasks",
            "agentic_django.views",
        },
        "src/agentic_django/tasks.py": {
            "agentic_django.models",
            "agentic_django.registry",
            "agentic_django.views",
        },
    }

    for path, forbidden in forbidden_imports.items():
        imports = imported_modules(path)
        violations = sorted(
            forbidden_module
            for forbidden_module in forbidden
            if has_import(imports, forbidden_module)
        )
        assert not violations, (
            f"{path} imports higher-level modules: {', '.join(violations)}. "
            "Keep the dependency direction in docs/architecture.md or document "
            "and test the new edge."
        )


def imported_modules(path: str) -> set[str]:
    tree = ast.parse(read_text(path), filename=path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def has_import(imports: set[str], module: str) -> bool:
    return any(
        imported == module or imported.startswith(f"{module}.")
        for imported in imports
    )
