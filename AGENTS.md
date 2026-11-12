# Agent guide (aa-demo)

<!-- launchpad:harness-start -->
## Harness (managed by launchpad — do not edit)

Shared rules: **`.cursor/rules/*.mdc`** (git submodule, pinned at **v0.5.12**).

Agent skills: **`prayog-skills/`** (git submodule at root, pinned at **v0.5.5**) — `/spec-draft`, `/initiative-feasibility`, `/spec-technical-review`, `/spec-implementation-plan`, `/pre-implement`, `/loop-spec`, `/learning-extract`, `/ground-spec`, `/purge-initiative-artifacts-app`, `/commit-workspace`, `/open-draft-pr`, `/create-board-tickets`.

**Do not edit** `.cursor/rules/`. Skill changes go upstream in prayog-skills.
Pin record: [`.harness-pin.yaml`](.harness-pin.yaml) (`profile: python-backend`).

### Delivery bootstrap

- Contract: **sdd-delivery/v2**
- Workflow: `prayog-skills/workflow.yaml`
- Pin record: `.harness-pin.yaml`
- Skill hub: `.harness/skills/`

When asked “what next?”, read the latest persistent handoff and the pinned
workflow, then explain the current stage, blockers, and next candidate. Do not
perform file or GitHub mutations unless the user explicitly authorizes them.

Development content skills only change the local workspace and record Forge
readiness. Branch/commit/push/PR/issue/label/merge happen only via forge skills
(`/commit-workspace`, `/open-draft-pr`, `/create-board-tickets`). Wave Draft PR
opens at `wave-pr-action` **after** `/loop-spec` (no mid-coding Draft PR). Do
not require a human `/open-draft-pr` when the pin sets `authorization: automated`
on that node — walkers may still run `/open-draft-pr`. Content skills must not
apply labels (including `wave-accepted`), commit, push, open/merge PRs, or update
boards — forge skills / human GitHub only. Wave tip approval is human-only at
`wave-acceptance` (label `wave-accepted`). Wave merge is human-only at
`wave-signoff` (publish only — not a second approve). Initiative-closure merges
are human-only at `initiative-closure-signoff-app` / `initiative-closure-signoff-meta`.

**PRs:** use `.github/pull_request_template.md` — Initiative, Spec path, Smoke command.

### Programme board

Engineering work is tracked on **[Engineering board](https://github.com/orgs/ankitv89/projects)** (org Project).

- SSOT: `aa-demo/config/governance-*.yaml` → `project_board` (read-only meta clone)
- Resolve binding: `launchpad board-bind --client <id>`
- After spec merge: `/create-board-tickets INIT-<id>` (forge; validates plan §9)
- Pass-1: `/pre-implement` → `/loop-spec` → `wave-pr-action` → `wave-acceptance`
  (smoke under `tests/verify` / `verify_command`, or P15 N/A; signal with label
  **`wave-accepted`** on the Draft PR tip)
- Pass-2: `/learning-extract` → `/ground-spec` → pin may `wave-done-action`
  (board → Done; not a slash skill) → `wave-signoff` (human merge only)
- Closure (all waves done, once): `initiative-closure` →
  `/purge-initiative-artifacts-app` → `initiative-closure-pr-action-app` →
  `initiative-closure-signoff-app` → `/purge-initiative-artifacts-meta` →
  `initiative-closure-pr-action-meta` → `initiative-closure-signoff-meta`.
  No required `/open-draft-pr` when pin `authorization: automated` on those PR nodes.
<!-- launchpad:harness-end -->

## Product (what to build)

Start here: [`docs/specification/README.md`](docs/specification/README.md)

| Layer | Entry point | Purpose |
|-------|-------------|---------|
| **Product specs** | [`docs/specification/product/`](docs/specification/product/) | What this service does |
| **As-built** | [`docs/specification/as-built/implementation-status.md`](docs/specification/as-built/implementation-status.md) | Live vs deferred; verification matrix |
| **ADRs** | [`docs/specification/adr/README.md`](docs/specification/adr/README.md) | Architecture decisions |

Active work: board issue **Spec path** → product initiative spec (from PRD handoff).

---

## Run and verify

- Setup/run source: [`README.md`](README.md)
- Canonical build/check/test commands: repository Makefile or package scripts
- Live verification and prerequisites: [`tests/README.md`](tests/README.md)

Use the repository commands exactly as documented; do not invent environment
activation, test, or verify commands.

---

## Before changing behavior

1. Read `.cursor/rules/code-guidelines-index.mdc` (or the profile’s rule index).
2. Read the relevant product spec and accepted ADRs.
3. Read as-built; do not infer live behavior from a spec.
4. Read `tests/README.md` and the repository Makefile/package scripts for exact commands.
5. Resolve the current delivery stage from the pinned Prayog workflow.

Do not edit pinned rules or skill sources. Product truth belongs in
`docs/specification/`; repository-specific commands remain in the repository.
