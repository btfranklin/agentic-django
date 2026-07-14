# Agentic Django Docs

This directory is the repo-local system of record for maintainers and coding
agents. Use the README for package users, then come here for current repository
structure, implementation boundaries, and validation rules.

## Start By Task

| Task | Read |
| --- | --- |
| Understand the package shape | [Architecture](architecture.md) |
| Change run/session/event behavior | [Architecture](architecture.md) and the matching tests |
| Change validation, CI, or release behavior | [Quality and validation](quality.md) |
| Prepare or change a release | [Releasing](releasing.md) |
| Update integration guidance for downstream Django apps | [Skill map](skills.md) and [integration skill](../skills/agentic-django-integration/SKILL.md) |
| Compare implementation to original design intent | [Historical design record](../AGENTIC_DJANGO_DESIGN.md) |

## Current Sources Of Truth

- [Architecture](architecture.md) describes the implemented package
  architecture,
  dependency directions, runtime flow, extension points, and security
  invariants.
- [Quality and validation](quality.md) describes the local validation loop, CI
  shape, and docs drift policy.
- [Releasing](releasing.md) describes the tag-first release process, release notes
  drafting, and PyPI publishing trigger.
- [Skill map](skills.md) describes how the embedded Codex skill and its reference
  files should stay aligned with package behavior.
- [AGENTS.md](../AGENTS.md) is only a short entry-point map.

## Maintenance Rule

When behavior changes, update the current-truth docs in the same change as the
code and tests. Keep planning or historical rationale out of current-truth docs
unless it directly explains the behavior future maintainers must preserve.
