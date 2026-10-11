# Tree Chat

Project steering lives in `.claude/steering/` and is imported below. Edit those files there; they are the source of truth for tech, requirements and design.

@.claude/steering/tech.md

**Work in progress:** see `HANDOVER.md` for the current state, the approved plan for steps 6 to 10 and the rules for continuing.

## Product

Tree Chat is a local, single-user chat client in which every tangent becomes a Branch anchored to the exact passage that prompted it. A Branch can be parked in a queue, resumed, and closed with a short Conclusion that is merged back into an ancestor as a Note. The conversation is a strict tree of Branches.

Messages are never edited or deleted: editing or regenerating creates an Alternative branch, and merging appends a Note. There is one context rule: every Branch inherits what its parent knew at its fork point, so each Branch's context only ever grows. What the model saw for every reply is recorded exactly (the Context_Manifest) and must be reproducible byte for byte.

Deliberately absent in v1: multiple users, sign-in, sync, mobile layout, multi-anchor branches, any context mode other than inheriting, and deletion. The app binds to 127.0.0.1 only.

## Feature workflow

Approach every new feature in this order. Do not skip ahead. Run steps 1-3 in one pass without pausing between them, editing the steering docs directly; put all open questions to the user together at step 3, not earlier. Step 4 is the approval gate: present the implementation steps in plan mode and write no code until the user approves.

1. **Requirements first.** Update `.claude/steering/requirements.md`: add the user story and acceptance criteria (EARS style: WHEN / IF / WHERE / WHILE ... THE system SHALL), add any glossary terms, and amend existing requirements the feature changes or contradicts.
2. **Design decisions.** Review the updated requirements, make any new design decisions, and record them in `.claude/steering/design.md`: the decisions table with rationale, architecture, API contract, data model, error handling, correctness properties and testing strategy as they apply. Update `.claude/steering/tech.md` if dependencies or commands change.
3. **Review the design.** Before devising implementation steps, re-read the design against the requirements: every acceptance criterion is covered, nothing contradicts an existing requirement or design decision, and open questions that only the user can answer are put to them.
4. **Implementation steps.** Only then devise the steps (no tasks file is kept), present them in plan mode for approval, then implement and test.
5. **Keep the docs true.** If implementation changes behaviour, update the requirements and design in the same change. Cite requirement numbers in code comments and tests.

Bug fixes and refactors that change no behaviour do not need steps 1-3.

If the owner explicitly waives steps 1-3 for a change ("no need for requirements first"), build it, say plainly which written requirements it contradicts, and bring the docs up to date afterwards at the owner's word. A waiver covers that change only.

## Spec

Requirements and technical design are imported below.

@.claude/steering/requirements.md
@.claude/steering/design.md

## Structure

Planned; created when the project is scaffolded.

```
treechat/            Python package (the Backend_API)
  domain/            pure logic: tree rules, Status machine, context assembly, rendering. No I/O, no clock, no ids.
  store/             the only code that touches SQLite; migrations in store/migrations/. No decisions.
  services/          one function per user operation, one transaction each. Never calls the provider directly.
  jobs/              reply and generated-text jobs; the only callers of the provider.
  provider/          Anthropic and Fake adapters; the only place credentials are read.
  api/               FastAPI routes and SSE framing. No business rules.
tests/               pytest + Hypothesis; synthetic data only. Live provider tests marked `live`.
web/                 Preact + TypeScript front end (Vite). Limits here are conveniences only.
data/                local Store file. Git-ignored; never committed.
.claude/steering/    tech, requirements and design: the source of truth.
```

## Conventions

- Only `store/` touches the database. Only `jobs/` (through `provider/`) calls the model. `domain/` is pure and holds every rule the product promises.
- Property-based tests (Hypothesis, including a stateful machine over all operations) are the primary evidence for `domain/`. A new test of a rule must be shown to fail when the rule is deliberately broken.
- Tests spend no AI credits: the default suite runs on the Fake provider and blocks real provider connections. The opt-in `live` tests (a few cents) run only when the owner says so.
- Never commit secrets, real customer data or real account data; tests use synthetic values.
- History is append-only. Messages and manifests are never updated or deleted (enforced by triggers). Migrations only add things, and a Store created by an earlier version must open and work.
- Never put anything volatile (time, ids, random order) into a rendered provider request. Rendering must be byte-deterministic.
- Cite requirement numbers in code comments and tests.

## Commands

`uv run treechat` (run), `uv run pytest` (test), `uv run pyright` (typecheck), `cd web && npm run build` (front end). Detail in tech.md.
