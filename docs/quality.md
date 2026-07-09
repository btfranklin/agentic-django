# Quality And Validation

This repository should stay easy for a future agent to validate without hidden
local knowledge.

## Local Validation

- Install: `pdm install --group dev`
- Lint: `pdm run lint`
- Test: `pdm run test`
- Full check: `pdm run check`

`pdm run check` is the canonical before-commit validation command. It runs lint
first, then the full pytest suite.

## Test Expectations

- Keep tests in `tests/` with `test_*.py` modules.
- Keep the suite offline and deterministic. Mock SDK/network behavior instead
  of making real API calls.
- Cover owner-scoped request access, session ordering, event serialization,
  cleanup/recovery commands, and settings validation when those contracts
  change.
- For migrations or long-running workflows, include success and failure-path
  regressions.

## CI And Release Shape

- `.github/workflows/python-package.yml` runs lint and tests on Python 3.12,
  3.13, and 3.14.
- `.github/workflows/python-publish.yml` builds with PDM and publishes through
  PyPI trusted publishing on release publication.
- `.github/workflows/draft-release-notes.yml` drafts notes when version tags are
  pushed.
- `docs/releasing.md` is the source of truth for release ordering. Push the
  version tag first so `release-notes-scribe` can populate the draft GitHub
  Release before publishing.

## Documentation Drift Rules

- `AGENTS.md` must stay a short routing map. Move durable detail into `docs/`.
- `docs/index.md` must link the current architecture, quality, release, and
  skill docs.
- `docs/architecture.md` is current truth for package boundaries and runtime
  flow.
- `docs/releasing.md` is current truth for tag, release notes, and publishing
  order.
- `AGENTIC_DJANGO_DESIGN.md` is historical design rationale. If it conflicts
  with `docs/architecture.md`, update the current architecture doc and either
  amend or clearly annotate the historical note.
- `skills/agentic-django-integration/references/` should match public README
  examples and implemented package behavior.

`tests/test_repo_legibility.py` enforces the highest-value documentation shape
so entry points do not drift back into stale or disconnected guidance.
