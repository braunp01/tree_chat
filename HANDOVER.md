# Handover: Tree Chat, steps 6 to 10

Written 11 Oct 2026 at the end of step 5. Read this first, then `CLAUDE.md` and the three files in
`.claude/steering/` (requirements, design, tech). Those four are the source of truth; this file only says where
the work stands and how to carry on.

## What this is

A local, single-user chat client. Every tangent becomes a **Branch** anchored to the passage that prompted it. A
Branch can be parked in a queue, resumed, and closed with a **Conclusion** that is merged into an ancestor as a
**Note**. The whole conversation is a strict tree, shown as a Branch_Graph (Outline and zoomable map in one pane) beside the Path_View. Every Branch
inherits what its parent knew at its fork point (one context rule, no modes). Messages are never edited or deleted.

## State at handover

Steps 0 to 5 of the approved plan are done and pushed to `main` (9 commits). Last commit: `f31a50d`.

| Step | Status | Where |
|---|---|---|
| 0 Scaffold | done | `pyproject.toml`, `treechat/`, `web/`, `tests/conftest.py` (network guard) |
| 1 Anchor spike | done | `web/src/markdown/`, `web/src/anchor/` (selection to source offsets, property-tested) |
| 2 Domain core | done | `treechat/domain/` (pure: model, rules, context, render, queue, prompts) |
| 3 Store | done | `treechat/store/` (SQLite schema with enforcing triggers, migrations, repo) |
| 4 Provider | done | `treechat/provider/` (Fake with API-rule checks, Anthropic adapter) |
| 5 Services and jobs | done | `treechat/services/`, `treechat/jobs/`, `tests/test_stateful.py` |
| 6 HTTP API | done (PR open) | `treechat/api/`, `treechat/services/views.py` (read models, documented in design.md) |
| 7 Front end: reading and writing | done (PR open, stacked on step 6) | `web/src/` (`api.ts`, `state.ts`, `components/`) |
| UI review | done (PR open, stacked on step 7) | One unified view: Branch_Graph beside the Path_View (`web/src/graph/`), top bar with Trees menu and Park/Resume/Reopen, exact-character underlines (`highlights.ts`). Req 18; Tree_Map merged into the graph pane |
| **8-10** | **next: step 8** | see below, with the changes noted under step 8 and 9 |

171 tests pass (`uv run pytest`, about 2.5 minutes), pyright strict and ruff are clean. 2 live tests are deselected.

## Rules of engagement (read these)

1. **Tests must cost no AI credits.** The default suite uses the Fake provider and `tests/conftest.py` blocks every
   non-loopback connection. Never set `ANTHROPIC_API_KEY` in the environment you work in. **Never run
   `pytest -m live`** (`tests/test_live.py`) unless the owner says so in chat. It makes at most 5 short real requests.
2. **Docs are the spec.** The implementation plan is approved (the steps below). If you change behaviour, change
   `requirements.md` and `design.md` in the same commit and cite requirement numbers in code comments and tests.
   Requirement numbers are permanent; retire, never renumber. A decision that contradicts the docs goes to the owner.
3. **Prove tests can fail.** After a new rule, break it on purpose, watch the test fail, restore it. This caught real
   bugs in steps 2, 4 and 5.
4. **One commit per finished step**, message ending with the attribution line your environment gives you. Work on a
   branch per step (`step-6-api`, ...) and open a PR into `main` so the owner can review. Do not push to `main`
   directly after this handover unless the owner says so.
5. **Layer rules** (`CLAUDE.md`): only `store/` touches SQLite; only `jobs/` calls the provider; `domain/` is pure
   (no I/O, no clock, no ids); `services/` never calls the provider; `api/` has no business rules.
6. **Say it plainly in reports.** Lead with the one-line answer, report outcomes faithfully (what failed, what could
   not be verified), no polishing.

## Commands

```bash
uv sync                          # Python 3.14 environment in .venv
uv run pytest                    # full default suite, no model calls
uv run pytest tests/test_x.py -q # one file
TREECHAT_STATEFUL_EXAMPLES=10 uv run pytest tests/test_stateful.py   # quicker stateful run
uv run pyright                   # strict on treechat/
uv run ruff format treechat tests && uv run ruff check treechat tests
cd web && npm ci && npm test && npm run build
TREECHAT_PROVIDER=fake uv run treechat        # serves http://127.0.0.1:8765, offline
```

Environment notes: `requires-python >= 3.14`. The code uses `uuid.uuid7()` (3.14 only) in `treechat/env.py`. If the
cloud image lacks Python 3.14 and `uv` cannot download it, tell the owner before lowering the requirement; the
fallback is a small local uuid7 helper in `env.py`. The project was developed on Windows, so line endings are
normalised by `.gitattributes` (`* text=auto eol=lf`).

## Things learned the hard way

- **Hypothesis stateful tests** are slow. Keep `TREECHAT_STATEFUL_EXAMPLES` low while iterating.
- **`JobRegistry.drain()`** must `await asyncio.sleep(0)` after `gather`, or it spins forever (already fixed).
- **Cache markers** are placed on the entry's own block, not the last block of a merged turn (already fixed).
- **A system message must be last or followed by an assistant turn.** A Framing_Block followed by a user turn is sent
  as labelled user text instead (`domain/render.py`). `FakeProvider` rejects any request the real API would reject.
- **Thinking blocks from another model** are not replayed (a refusal fallback can serve a reply).
- **Req 2.9:** a Branch whose last message is an unanswered user message accepts no further user message and no merge
  Note. The close panel must offer to request the reply first.
- **Merging with no target** defaults to the parent; if the parent is closed the service raises `merge_target`
  validation. The UI must then offer another open ancestor.
- Shell heredocs with long bodies broke once under the Bash tool; write files with the file tools.
- Ruff line length is 120; pyright is strict on `treechat/` (tests are checked non-strict).

## How the pieces connect (for step 6)

```python
from treechat.config import load_config
from treechat.env import system_env
from treechat.store.db import Store
from treechat.provider import make_provider
from treechat.jobs.registry import JobRegistry
from treechat.services.ctx import Ctx
from treechat.domain.model import Settings

cfg = load_config()
registry = JobRegistry()
ctx = Ctx(Store(cfg.db_path), system_env(), Settings(cfg.model, cfg.effort), registry.is_busy)
provider = make_provider(cfg)
```

- **Services** (`treechat/services/`): `trees.create_tree / rename_tree`, `messages.send_message / prepare_reply /
  edit_message / regenerate_message`, `branches.spawn_tangent / change_status / set_intent / set_fork_point`,
  `closing.close_branch`, `drafts`. They raise `DomainError` subclasses (`ValidationError` with `.fields`,
  `Conflict`, `NotFound`, `Busy`, each with `.category` and `.message`).
- **Replies:** `registry.start_reply(ctx, provider, branch_id)` validates, then runs the reply in the background and
  returns a `ReplyJob`. `async for ev in job.stream()` yields `started`, `delta`, `done` or `error` events and can be
  called again after a disconnect (catch-up first). `registry.get(branch_id)` finds a running job.
- **Generated text:** `jobs.replies.generate_intent` (call in the background after spawning a Tangent with no
  Intent, Req 11.1), `generate_standing` (after parking a Tangent that has replies, Req 11.2),
  `draft_conclusion` (on request, not stored, Req 12.1). Use `registry.spawn_background(...)`.
- **Reads:** `store.repo.load_snapshot(conn, tree_id)` returns an immutable `TreeSnapshot`; the pure functions in
  `domain/rules.py`, `domain/context.py`, `domain/queue.py` compute everything else. Manifests:
  `repo.get_manifest`. Previews: `repo.message_preview`. Closings: `repo.closings_for`. Generated text:
  `repo.latest_generated`. Tree list: `repo.list_trees`.
- **Message JSON:** `jobs.replies.message_out(message)`.

## Step 6: HTTP API (`treechat/api/`)

Implement exactly the contract in `design.md` > Components and Interfaces > API Contract, plus the two extra routes
already listed there (`/map`, `/messages/{id}/preview`, and `/api/health`, which exists).

- App factory in `api/app.py` (exists). Add a FastAPI **lifespan** that builds `Store`, `JobRegistry`, `Ctx`, the
  provider, and drains the registry on shutdown. Keep it testable: `create_app(config=None)` must work with a temporary
  database and the fake provider, and tests need access to the `FakeProvider` instance to script outcomes.
- **Error mapping:** `DomainError.category` to HTTP: `validation` 422, `not_found` 404, `conflict` 409, `busy` 409,
  `context_too_large` 422, `provider_unavailable` 503, `provider_error` 502, `refused` 502. Body
  `{ "error": category, "fields": [...], "message": "..." }`. Request-body validation errors must also use this
  shape and name the field (Req 4.5, 12.2).
- **SSE** for `POST /api/branches/{id}/reply` and `GET /api/branches/{id}/live` (204 when no job). Call
  `registry.start_reply` before returning the stream so Conflict/Busy become ordinary HTTP errors. One JSON object per
  `data:` line. Disconnecting must not cancel the job (Req 2.6).
- **Side effects of routes:** spawn without an Intent starts `generate_intent` in the background; park starts
  `generate_standing`; `conclusion-draft` awaits `draft_conclusion` and returns `{ "text": ... }` (an empty string if
  the provider is unavailable, so the close panel still works).
- **Read models (define the JSON, then document it in `design.md`):**
  - `GET /api/trees`: id, title, counts of open and parked Branches (Req 1.2).
  - `GET /api/trees/{id}`: every Branch summary for the Outline (Req 14.1): id, parent, kind, status, depth, intent,
    generated intent (labelled), anchor quote, message count, parked time, closing records.
  - `GET /api/branches/{id}/view` (Req 5, 14.4): the inherited entries collapsed with a count and the anchor message
    always included, the framing card, own messages with their Anchor_Markers (child Branches anchored in each
    message: offsets, status, intent), Notes with a link to the source Branch, Alternatives per message (Req 3.4).
  - `GET /api/trees/{id}/queue?order=oldest|newest|parent` (Req 10.2, 10.4, 10.5): intent, generated intent, standing
    line, anchor quote, parent, time parked, `parent_messages_since_fork`. `domain/queue.py` already orders.
  - `GET /api/trees/{id}/map` (Req 14.8 to 14.18): per Branch its parent, anchor `conversation_position`, start
    position, message count, status, intent; per Message its role and position and no content. Compute positions in
    one pass; `domain.rules.conversation_position` is O(depth) per call and too slow for 10,000 messages.
  - `GET /api/messages/{id}/manifest` (Req 7.8) and `/preview` (first 200 characters, Req 14.14).
- **Static serving:** `uv run treechat` serves `web/dist` at `/` (already wired). Bind to 127.0.0.1 only.
- **Tests** (`tests/test_api.py`, FastAPI `TestClient`, temporary database, fake provider): the full flow
  send, reply, spawn, close and merge; every route's error shape; `busy`; disconnect then `/live`; a provider
  failure that leaves the user Message; validation errors name the right field; the generated-intent side effect;
  the read models on a seeded tree. No test may call a real provider.
- **Checkpoint:** stop and report after step 6 (back end complete) with a short curl demo against the fake provider.

## Steps 7 to 10 (unchanged from the approved plan)

**7. Front end: reading and writing** (`web/src/`, Preact + TypeScript + signals; the Vite proxy sends `/api` to
8765). Tree list (Req 1.2). Path_View: collapsed inherited prefix with the anchor message always visible, framing
card, own messages rendered with `web/src/markdown/MarkdownView.tsx`. Composer with streaming and a "cut off" mark on
`max_tokens` (Req 2.4). Anchor_Markers (Req 5). Selection popover using `anchorFromRange`: Enter parks, Ctrl/Cmd+Enter
opens, Escape cancels, `fork_at` choice, and the "N notes after this passage, fork at latest instead?" hint (Req 4.10).
Alternatives switcher (Req 3.4) and manifest inspector (Req 7.8).

**8. Front end: closing and the Queue (reduced by the UI review).** Already done in the UI review: Outline as the Branch_Graph with keyboard control (Req 14.1, 14.2, 14.6, 18), breadcrumb (14.3), depth and open/parked counts (15.1), Park/Resume/Reopen buttons. Remaining: the Queue with three orderings, staleness facts, resume with the offer to re-fork at the Tip, close from the Queue (Req 10); the close panel with model-drafted conclusion, outcome, merge-target picker (open ancestors only), abandon descendants, then navigate to the anchor (Req 12, 13); one-key Close and the nudge after 8 replies (Req 15.2-15.3, `TREECHAT_NUDGE_AFTER`).

**9. Later enhancement of the Branch_Graph (formerly the separate Tree_Map).** The graph pane already pans, zooms, fits and enlarges with `M` (Req 14.8, 14.17, 18.11). What is left is optional and was deferred by the owner's "one unified view": size-based collapsing of subtrees (Req 14.10-14.12, 14.18), message ticks inside nodes (14.14) and grouping of very many siblings (a 175-child Trunk is a tall column). Do this only if the owner asks after using the graph. Pure functions live in `web/src/graph/visible.ts` and `layout.ts` with Properties 17-19.

**10. Finish.** `scripts/seed_synthetic.py` (fake provider, zero credits) builds a Tree with 500 Branches and 10,000
Messages for the manual performance and readability check (Req 14.7, 14.17). Search all docs for wording the build
made untrue and fix it; run the end-of-change checklist in the old template README (requirements amended, design
rows replaced, citations in code, full suite and build pass, scratch data removed).

## Definition of done for each step

`uv run pytest`, `uv run pyright`, `uv run ruff check treechat tests` pass; `cd web && npm test && npm run build`
pass once the front end exists; mutation spot-checks done for new rules; docs updated; one commit; report says what
was verified and what only the owner can check on their own screen (for example how the UI feels).

## Known limits and open items

- Real-API behaviour is unverified: the live tests have never been run. The adapter is tested only against canned
  HTTP responses. Ask the owner before running them.
- The Tree_Map assumes SVG is fast enough at 500 Branches; if it misses 30 fps, move drawing to Canvas (layout and
  level of detail are unaffected).
- Anchors across unusual markdown (tabs, quotes nested in lists, raw HTML blocks, autolinks, setext headings) fall
  back to the whole text run; not covered by the generator yet.
- Deletion of Trees, Branches and Messages is deliberately absent in v1 (Req 16.3).
- Owner's explicit decisions are recorded in the "Key Design Decisions" table in `design.md`; do not reopen them.
