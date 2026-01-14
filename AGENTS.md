# Repository Guidelines

## Project Structure & Module Organization
- The package uses a src layout; keep app code in `src/agentic_django`.
- Keep migrations in `src/agentic_django/migrations` and templates under `src/agentic_django/templates/agentic_django`.
- Store uncompiled front-end assets in `assets/` and deposit build outputs into `static/` when introducing UI assets. Keep runtime collections such as `staticfiles/` and user uploads (`media/`) outside of version control.
- Keep architecture notes and design docs in this repo (e.g., `AGENTIC_DJANGO_DESIGN.md`) and update them before major refactors.

## Build, Test, and Development Commands
- Use PDM to capture application and dev-only dependencies. Document the canonical install command (e.g., `pdm install --group dev`).
- Target runtimes: Python 3.12+ always; use Django 6.x for Django services unless explicitly scoped otherwise.
- Enforce version policy in `pyproject.toml`: set `requires-python = ">=3.12"` and pin Django to `>=6,<7` (or the project’s chosen minor track).
- Expose a single test runner command (`pdm run test`) for the package.
- Expose a lint command (`pdm run lint`) for the package.

## Coding Style & Naming Conventions
- Use 4-space indentation, type-annotate every function, and prefer built-in generics (`list[str]`, `dict[str, Any]`) with `| None` for optionals on Python 3.12+.
- Keep Django apps modular: new views, forms, services, and tasks should live under the app that owns the corresponding data or workflow.
- Prefer Django 6’s built-in tasks framework for background work; introduce Celery only when its operational guarantees/features are required.
- Follow a predictable template hierarchy (`<app>/templates/<app>/**`) and colocate HTMX or partial templates alongside the features that render them.
- Prefer Django 6 template partials (`{% partialdef %}` / `{% partial %}`) before splitting markup into many tiny `{% include %}` files.
- Enable Django 6’s built-in Content Security Policy support by default where feasible; tighten policies and selectively open `script-src`/`connect-src` per feature.
- Avoid relying on undocumented Django email internals; Django 6 modernizes the email API implementation, so keep custom backends/subclasses conservative.
- Explicitly set `DEFAULT_AUTO_FIELD` (or accept the BigAutoField default) to keep migrations deterministic across apps.
- Treat the linter as non-optional. Run it locally before committing; unresolved linting errors should block CI.
- Write docstrings and comments in American English; focus on clarifying intent rather than restating code.

## Testing Guidelines
- Keep tests adjacent to their code (`tests/` for the package). Name modules `test_*.py`, classes `Test*`, and functions `test_*` for automatic discovery.
- Cover asynchronous tasks, external service adapters, and LLM helpers with deterministic fixtures. Mock network-bound APIs so the suite stays offline and fast.
- When adding migrations or long-running flows, include regression tests that exercise both success and failure paths.
- Make `pdm run test` (or the equivalent) the default validation step before pushing changes.

## Commit & Pull Request Guidelines
- Favor concise, sentence-case commit messages that describe both the change and its intent (e.g., `Add credit balance tracking to user profiles`).
- Keep commits scoped to a single concern. Mention the affected app or feature area when useful for reviewers.
- Pull requests should summarize the change set, call out new migrations, list manual or automated test results, and attach UI screenshots or logs for behavioral updates.
