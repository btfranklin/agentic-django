# Embedded Integration Skill

This repo ships a Codex skill at `skills/agentic-django-integration/` for agents
that are integrating the package into downstream Django projects.

## Skill Entry Point

- `skills/agentic-django-integration/SKILL.md` is the short task-oriented
  entry point.
- `skills/agentic-django-integration/references/` contains deeper topic
  references.

## Reference Roles

| Reference | Purpose |
| --- | --- |
| `quickstart.md` | Minimal install, URL, settings, and migration setup. |
| `registry.md` | Host-app agent registry callable patterns. |
| `htmx.md` | Polling fragments, coordinated updates, and template usage. |
| `events.md` | Event persistence, event endpoint, and signal usage. |
| `operations.md` | Cleanup, retention, and stuck-run recovery commands. |
| `architecture.md` | Downstream-facing runtime flow and concurrency notes. |
| `data-model.md` | Model/session/serialization invariants. |
| `errors-security.md` | Error handling, owner scoping, and safety guidance. |

## Maintenance Rules

- Keep the skill focused on downstream integration. Repo-maintenance guidance
  belongs in `docs/`.
- When changing settings, endpoints, signals, models, or management commands,
  update the relevant skill reference in the same change.
- When changing README integration examples, check whether the skill quickstart
  or HTMX/event references need the same update.
- Do not let the skill become a second architecture doc for this repo. Link back
  to `docs/architecture.md` when maintainers need package-internal details.
