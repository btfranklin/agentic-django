from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\((?P<target>[^)\s]+)")

CORE_LEGIBILITY_ARTIFACTS = {
    Path("AGENTS.md"),
    Path("README.md"),
    Path("docs/architecture.md"),
    Path("docs/index.md"),
    Path("docs/quality.md"),
    Path("docs/releasing.md"),
    Path("docs/skills.md"),
    Path("AGENTIC_DJANGO_DESIGN.md"),
    Path("skills/agentic-django-integration/SKILL.md"),
}

REQUIRED_ROUTES = {
    "AGENTS.md": CORE_LEGIBILITY_ARTIFACTS - {Path("AGENTS.md"), Path("docs/index.md")},
    "docs/index.md": {
        Path("AGENTS.md"),
        Path("docs/architecture.md"),
        Path("docs/quality.md"),
        Path("docs/releasing.md"),
        Path("docs/skills.md"),
        Path("AGENTIC_DJANGO_DESIGN.md"),
        Path("skills/agentic-django-integration/SKILL.md"),
    },
}

LINK_CHECK_DOCUMENTS = {
    *REQUIRED_ROUTES,
    "docs/quality.md",
    "docs/releasing.md",
    "AGENTIC_DJANGO_DESIGN.md",
}


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_core_legibility_artifacts_exist() -> None:
    missing = sorted(
        str(path) for path in CORE_LEGIBILITY_ARTIFACTS if not (ROOT / path).is_file()
    )

    assert not missing, f"Missing core repository guidance: {', '.join(missing)}"


def test_agents_md_stays_short() -> None:
    agents = read_text("AGENTS.md")

    assert len(agents.splitlines()) <= 80, (
        "Keep AGENTS.md as a short routing map; move durable guidance into docs/."
    )


def test_repository_routes_are_resolved_markdown_links() -> None:
    links_by_source = {
        source: local_markdown_targets(source) for source in LINK_CHECK_DOCUMENTS
    }

    for source, linked_targets in links_by_source.items():
        broken_routes = sorted(
            str(path) for path in linked_targets if not (ROOT / path).exists()
        )
        assert not broken_routes, (
            f"{source} contains broken local links: {', '.join(broken_routes)}"
        )

    for source, required_targets in REQUIRED_ROUTES.items():
        linked_targets = links_by_source[source]
        missing_routes = sorted(str(path) for path in required_targets - linked_targets)

        assert not missing_routes, (
            f"{source} must link to: {', '.join(missing_routes)}"
        )


def test_pyproject_exposes_canonical_validation_scripts() -> None:
    config = tomllib.loads(read_text("pyproject.toml"))
    scripts = config["tool"]["pdm"]["scripts"]

    assert scripts["lint"] == "ruff check src tests"
    assert scripts["test"] == "pytest"
    assert scripts["check"]["composite"] == ["lint", "test"]
    assert config["tool"]["pdm"]["version"]["source"] == "scm"


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


def local_markdown_targets(path: str) -> set[Path]:
    source = ROOT / path
    targets: set[Path] = set()

    for match in MARKDOWN_LINK.finditer(source.read_text(encoding="utf-8")):
        destination = urlsplit(match.group("target"))
        if destination.scheme or destination.netloc or not destination.path:
            continue

        resolved = (source.parent / unquote(destination.path)).resolve()
        try:
            targets.add(resolved.relative_to(ROOT))
        except ValueError as error:
            raise AssertionError(
                f"{path} contains a local link outside the repository: "
                f"{match.group('target')}"
            ) from error

    return targets
