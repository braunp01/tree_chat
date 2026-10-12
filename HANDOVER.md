# Handover: Tree Chat v2

Written 12 Oct 2026, when the v2 rebuild was finished. Read this first, then `CLAUDE.md` and the three files in
`.claude/steering/` (requirements, design, tech). Those four are the source of truth. This file only says where the
work stands and how to carry on.

## What this is

An ordinary chat whose conversations are trees. There are two actions: navigate to any earlier reply, and send
from it, which adds a new child. Nothing is edited, regenerated or deleted.

- Each Tree has one Root (the first message typed), and the Trees menu lists the forest.
- The model sees exactly the Path from the Root to the question.
- The Branch_Graph beside the chat shows derived Branches and navigates them.

v1 (tangents anchored to passages, parking, closing, merging) was withdrawn by the owner on 12 Oct 2026. It is in git
history: `main` at 1e59794, plus the branches `step-6-api` and `ui-branch-graph`.

## State

All of the approved v2 plan is done on branch `message-tree`, one PR into `main`.

| Area | Where |
|---|---|
| Steering v2 | `.claude/steering/` (Req 1-8, design decisions, Properties 1-8) |
| Store | `treechat/store/` (new schema in `data/tree_chat_v2.sqlite3`; triggers enforce Req 5; a v1 file is refused) |
| Domain | `treechat/domain/` (path, check_parent, default_point, latest_reply_below, branches, assemble, render) |
| Services and jobs | `treechat/services/`, `treechat/jobs/` (registry keyed by user Message) |
| API | `treechat/api/` (contract in design.md) |
| Front end | `web/src/` (`App.tsx`, `components/Chat.tsx`, `components/TopBar.tsx`, `graph/`, `state.ts`, `api.ts`) |
| Seed for the speed check | `scripts/seed_synthetic.py` |

Verified at handover:

- Python checks:
  - `uv run pytest`: 93 passed; 2 live tests deselected and never run.
  - `uv run pyright`: 0 errors.
  - `uv run ruff check`: clean.
- Front end: `cd web && npm test` gives 48 passed, and `npm run build` succeeds.
- Mutation checks: every new rule was broken on purpose and a test failed.
  - Back end: shape triggers, context = Path, cache breakpoint, default point, latest below, busy, live re-attach.
  - Front end: sibling order, neighbourhood, path not collapsible, hidden counts, node goes to the end of its Branch, branch hint, composer lock, "go back" only on earlier replies, Reply becomes the Current_Point, default point, navigation applied at once.
- Chromium smoke on the Fake provider:
  - three turns;
  - go back to the first reply and send, which makes a fork (3 graph nodes);
  - click the original Branch, which is intact (6 messages);
  - "see what was sent" lists 5 entries;
  - "New tree" then send gives a second Tree in the menu;
  - no console errors.
- Req 6.11, on the seeded Tree (500 Branches, 10,720 Messages), headless Chromium in the cloud container:
  - opening takes 253 ms;
  - moving the Current_Point takes 82-129 ms;
  - all 500 nodes drawn;
  - panning runs at 61 fps.
  - **The owner's own machine is not measured.**

Not verified:

- **Real-API behaviour.** The live tests have never been run. Ask the owner before running `uv run pytest -m live`.
- **How the UI feels on the owner's screen.**

## Rules of engagement

1. **Tests cost no AI credits.** The default suite uses the Fake provider, and `tests/conftest.py` blocks every
   non-loopback connection. **Never run `pytest -m live`** unless the owner says so in chat.
2. **Docs are the spec.** Follow the feature workflow in `CLAUDE.md`. If behaviour changes, change `requirements.md`
   and `design.md` in the same commit. Cite requirement numbers in code comments and tests. Requirement numbers are
   permanent: retire them, never renumber.
3. **Prove tests can fail.** After adding a rule, break it on purpose, watch a test fail, then restore it.
4. Work on a branch and open a PR into `main`. End commit messages with the attribution lines your environment
   gives you.
5. **Layer rules** (`CLAUDE.md`):
   - Only `store/` touches SQLite.
   - Only `jobs/` calls the provider.
   - `domain/` is pure: no I/O, no clock, no ids.
   - `api/` holds no business rules.
6. **Report plainly.** Say what failed and what could not be verified.

## Commands

```bash
uv sync
uv run pytest                                               # about 75 s; no model calls
TREECHAT_STATEFUL_EXAMPLES=10 uv run pytest tests/test_stateful.py   # quicker stateful run
uv run pyright && uv run ruff check treechat tests scripts && uv run ruff format --check treechat tests scripts
cd web && npm ci && npm test && npm run build
TREECHAT_PROVIDER=fake uv run treechat                      # http://127.0.0.1:8765, offline
uv run python scripts/seed_synthetic.py data/seed.sqlite3   # then TREECHAT_DB=data/seed.sqlite3
```

On Windows PowerShell, set variables with `$env:TREECHAT_PROVIDER="fake"`.

## Things learned the hard way

- **Navigation must take effect at once.** The front end used to apply a route only on `hashchange`, so a quick
  send after "New tree" went into the old Tree. `navigate()` now applies the route synchronously, and opening
  another Tree clears the old Path first (`web/src/state.test.ts`, "leaving a point").
- **A test that holds the FakeProvider gate must release it in `finally`.** Otherwise the fixture's
  `registry.drain()` waits forever and the whole run hangs (`tests/test_api.py`, `_busy_then_live`).
- **`JobRegistry.drain()`** must `await asyncio.sleep(0)` after `gather`, or it spins.
- **Thinking blocks from another model are not replayed.** A refusal fallback can answer with another model.
  `FakeProvider` rejects any request the real API would reject.
- **Preact sets SVG attributes verbatim.** Use lowercase `tabindex` on SVG elements.
- **Killing processes.** `pkill` can kill the tool's own shell; kill the server by PID.
- **Style limits.** Ruff line length is 120. Pyright is strict on `treechat/`.

## Known limits and open items

- **Real API unverified** (see above).
- **Graph granularity.** The graph works at the level of Branches. Going back within one Branch moves the chat but
  not the highlighted node. This is as designed (Req 6.2).
- **Hidden Branches are counted, not named.** Expanding a collapsed node lists them.
- **Old PRs.** PRs for `step-6-api` and `ui-branch-graph`, and the `conversation-first` WIP, belong to v1. Ask the
  owner before closing them.
