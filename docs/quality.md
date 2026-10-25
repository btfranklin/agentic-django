# Quality And Validation

This repository should stay easy for a future agent to validate without hidden
local knowledge.

## Local Validation

- Install: `pdm install --group dev --group rq`
- Lint: `pdm run lint`
- Type check: `pdm run typecheck`
- Documentation: `pdm run docs`
- Test: `pdm run test`
- Full check: `pdm run check`

`pdm run check` is the canonical before-commit validation command. It runs lint
first, then strict Mypy, the offline documentation check, and the full pytest suite.

## Type Safety

Mypy checks all package code, migrations, tests, and subprocess scenarios. The
Django plugin uses `tests.settings`. The Pydantic plugin checks model constructor
arguments. Strict mode is enabled. Explicit `Any` and types lost through missing
imports are errors. Do not add broad module exclusions or ignore missing imports.

Use SDK types for agents, sessions, input items, and results. Use `JsonValue` and
`JsonObject` from `agentic_django.types` for JSON data. Use `TypedDict` for known
field structures. Accept `object` for an unknown value, then validate and narrow
its type before use. Do not replace a known structure with `dict[str, object]`.

Settings and decoded request data are checked at runtime. Session reads validate
stored items against the SDK input schema. Host serializers must implement the
protocols in `agentic_django.serializers`. Their persisted results must be JSON
data. The registry checks keys and factories and checks each returned agent.
The host app must keep its agent context type consistent with its context factory.
Python cannot check that relationship across dynamically imported components.

Keep exceptions on individual lines and state their cause:

- The asgiref internal thread handler is untyped. One call exception and one
  return cast preserve its callable's result type. A second exception permits
  `CurrentThreadExecutor`, which implements the executor interface but is not
  the `ThreadPoolExecutor` named by asgiref's annotation.
- The validated SDK `RunConfig` subclass inherits SDK fields that use `Any`.
  One exception permits its generated constructor. JSON configuration is checked
  against the SDK dataclass fields. No package data uses explicit `Any`.
- The SDK error-handler cast applies to dynamic callbacks. Runtime checks
  cannot establish their full Python signatures and annotations.
- Tests for custom user models need local assignment exceptions where Django
  stubs resolve the user to the single model in `tests.settings`. The custom
  user test also removes the inherited username field with a local exception.
- The cancelled-model test uses an unreachable `yield` to declare an async
  generator that always raises. One exception marks that required declaration.

## Documentation Check

Install Perfect Doc 0.1.0 or later and place `perfect-doc` on `PATH`. For example,
use `brew install btfranklin/tap/perfect-doc`. CI builds the tagged release with
Cargo. The offline command is `perfect-doc check --offline --no-banner`.

`perfect-doc.toml` checks Markdown sources with GFM and GitHub anchors. Python
package directory links resolve through `__init__.py`. Django templates are not
static documentation; template rendering remains covered by pytest.

## Test Expectations

- Keep tests in `tests/` with `test_*.py` modules.
- Keep the suite offline and deterministic. Mock SDK/network behavior instead
  of making real API calls.
- Keep isolated subprocess scenarios in `tests/scenarios/` as normal Python
  modules. Launch them with `python -m` so Django setup remains isolated and
  the scenario code remains covered by lint.
- Cover owner-scoped request access, session ordering, event serialization,
  cleanup/recovery commands, and settings validation when those contracts
  change.
- Cover repeated async client calls, concurrent bridge calls, process forks,
  stream cancellation, and large immediate-backend backlogs. Local loopback
  HTTP servers can verify connection reuse without a provider API key.
- Cover custom user models, nullable output fields, malformed JSON, query
  limit overflow, and multipart forms with CSRF checks enabled.
- Test admin action permissions, saves that race with worker completion,
  anonymous and cross-owner requests, cleanup races, and interrupted queue
  submissions. The RQ test loads the backend and
  submits the package task with a mocked queue; it does not need Redis. CI
  installs the RQ extra so this test cannot be skipped for a missing dependency.
- For migrations or long-running workflows, include success and failure-path
  regressions.

## CI And Release Shape

- [Python package workflow](../.github/workflows/python-package.yml) runs lint, strict type checks,
  and tests on Python 3.12, 3.13, and 3.14.
- The same workflow runs the offline documentation check in a separate job.
- [Python publishing workflow](../.github/workflows/python-publish.yml) builds
  with PDM and publishes through PyPI trusted publishing on release publication.
- [Draft release workflow](../.github/workflows/create-draft-release.yml) drafts
  notes when version tags are pushed.
- [Releasing](releasing.md) is the source of truth for release ordering. Push the
  version tag first so `release-notes-scribe` can populate the draft GitHub
  Release before publishing.

## Documentation Drift Rules

- [AGENTS.md](../AGENTS.md) must stay a short routing map. Move durable detail
  into `docs/`.
- [Documentation index](index.md) must link the current architecture, quality,
  release, and skill docs.
- [Architecture](architecture.md) is current truth for package boundaries and runtime
  flow.
- [Releasing](releasing.md) is current truth for tag, release notes, and publishing
  order.
- [Historical design record](../AGENTIC_DJANGO_DESIGN.md) is historical design
  rationale. If it conflicts with [architecture](architecture.md), update the
  current architecture doc and either amend or clearly annotate the historical
  note.
- `skills/agentic-django-integration/references/` should match public README
  examples and implemented package behavior.

`tests/test_repo_legibility.py` enforces core artifact existence, resolved local
links, parsed project configuration, and package dependency direction. It does
not enforce documentation wording.
