# Agent Guide

This repository is the reusable `agentic_django` Django app. Keep this file as
a short routing map. Durable architecture, quality, and integration guidance
belongs in the docs it links to.

## Start Here

- User-facing package overview: `README.md`
- Current architecture map: `docs/architecture.md`
- Validation and maintenance rules: `docs/quality.md`
- Embedded integration skill map: `docs/skills.md`
- Embedded integration skill entry point:
  `skills/agentic-django-integration/SKILL.md`
- Historical design rationale: `AGENTIC_DJANGO_DESIGN.md`
- Package code: `src/agentic_django/`
- Tests: `tests/`

## Commands

- Install dev dependencies: `pdm install --group dev`
- Lint: `pdm run lint`
- Test: `pdm run test`
- Full local validation: `pdm run check`

Use PDM for Python dependency and environment management. When adding
dependencies, use the newest available version and prefer `>=` ranges unless a
bounded compatibility track is required, such as `Django>=6,<7`.

## Repo Boundaries

- Runtime package code lives under `src/agentic_django/`.
- Migrations live under `src/agentic_django/migrations/`.
- Package templates live under `src/agentic_django/templates/agentic_django/`.
- Package static files live under `src/agentic_django/static/agentic_django/`.
- Integration-skill guidance lives under `skills/agentic-django-integration/`.
- Cross-cutting docs live under `docs/`; update them before major refactors.

## Coding Expectations

- Target Python 3.12+ and Django 6.x.
- Type-annotate functions and use built-in generics (`list[str]`,
  `dict[str, Any]`) with `| None` for optionals.
- Prefer Django 6 tasks for background work; introduce Celery only if a host app
  needs its operational guarantees.
- Keep request-facing code owner-scoped. Views and queries that expose sessions,
  runs, or events must filter by `owner`.
- Treat lint failures as blockers.

## Documentation Policy

- `docs/architecture.md` is the current-truth architecture map.
- `AGENTIC_DJANGO_DESIGN.md` is historical design rationale; do not treat it as
  the only current source.
- Update `docs/quality.md` when validation, CI, release, or maintenance rules
  change.
- Keep the embedded skill references synchronized with public README examples
  and current package behavior.
