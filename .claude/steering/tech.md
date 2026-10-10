# Technology Stack

<!--
What this file is for: everything a newcomer needs to build, run and test the project, and
nothing about behaviour (that is requirements.md) or reasons (that is design.md).
Update it in the same change that adds a dependency, a command or a setting.
-->

> **Status: approved by the owner, 11 Oct 2026.** Nothing is installed yet. Exact versions are pinned when the project is scaffolded.

## Language & Runtime

- Python 3.14 (back end). The environment is `.venv/` in the project root, created by `uv sync`. uv 0.12 is already installed on this machine.
- Node 24 (front-end build only; not needed at run time). Dependencies go in `web/node_modules/`, created by `npm ci`.

## Dependencies

Python pins live in `pyproject.toml`, locked in `uv.lock`. Front-end pins live in `web/package.json`, locked in `web/package-lock.json`. Change a pin only in its own commit, and run the full test suite on it. Lock files are committed.

Runtime (Python):

- `fastapi` (HTTP API, request validation)
- `uvicorn` (ASGI server)
- `anthropic` (official Claude SDK: streaming, thinking blocks, prompt caching, fallbacks)
- `sqlite3`, `uuid` (`uuid7`) from the standard library (the Store and ids)

Test only (Python, the `dev` dependency group):

- `pytest` (test runner)
- `hypothesis` (property-based and stateful tests)
- `httpx` (FastAPI test client)
- `pyright` (strict type checking)
- `ruff` (lint and format)

Front end (`web/`): TypeScript, Preact, `@preact/signals`, `mdast-util-from-markdown` and `mdast-util-gfm` (markdown parsed with source positions), and Vite (build and dev server). Tests use Vitest and fast-check.

## Common Commands

```bash
uv sync
uv run pytest
uv run pytest -m live
uv run pyright
cd web && npm ci && npm run build
uv run treechat
```

- `uv run pytest` makes **no** model calls (Fake provider; real provider connections are blocked).
- `uv run pytest -m live` is the optional live check: at most 6 short requests, a few cents. **Run it only when the owner says so.**
- `uv run treechat` serves the API and the built front end on http://127.0.0.1:8765.
- For front-end development, run `npm run dev` in `web/`. It runs the Vite dev server with `/api` proxied to the back end.

## Settings and environment variables

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | **Secret.** Provider credential. Lives in the user's environment or the `ant auth login` profile, never in the repository or the Store. Without it, the app starts but replies fail with `provider_unavailable`. |
| `TREECHAT_DB` | `data/tree_chat.sqlite3` | Path to the Store. `data/` is git-ignored. |
| `TREECHAT_PORT` | `8765` | Port on 127.0.0.1. |
| `TREECHAT_MODEL` | `claude-opus-5-5` | Model id for all generation. |
| `TREECHAT_EFFORT` | `high` | Effort level for replies. |
| `TREECHAT_NUDGE_AFTER` | `8` | Replies in a Tangent before the close/park nudge; `0` turns it off (Req 15.2). |
| `TREECHAT_PROVIDER` | `anthropic` | `fake` gives deterministic offline replies (Req 17.4). The tests always use `fake`. |

## Hosting

Not hosted. The app runs locally on the owner's Windows machine. Back up the Store by copying `TREECHAT_DB` while the app is stopped.

## Launch Shortcut

When the user's prompt is just `l` or `launch`, start the application and show it in the built-in browser pane.

<!--
Lessons from the version this came from; keep the ones that apply:
- Aim for as few tool calls as possible (one to start, one to open the page). Do not inspect
  processes, read logs or probe ports separately first: that detour once took minutes.
- Check HEALTH, not just that a port is in use. A hung server can accept connections and never
  answer. Probe with a short timeout every time and never call a server without one.
- Reuse a running server only if it is healthy AND was started the way development needs
  (for example with auto-reload); otherwise stop it and start fresh, so edits are not ignored.
- Start servers detached, with output in a log file, so the same call can wait for readiness.
- When killing processes, filter by process name, not only by command line: the tool's own
  shell can contain the script text and match itself.
- Report the URL, whether it loaded, and anything wrong; do not run tests or change code unless asked.
-->

1. `preview_start` with the `treechat` entry in `.claude/launch.json`. It runs `uv run treechat --reload` on port 8765 and waits for `GET /api/health` to answer within 2 seconds. (The entry and the health endpoint are created when the project is scaffolded.)
2. Open http://127.0.0.1:8765, take a small screenshot and read console errors.
