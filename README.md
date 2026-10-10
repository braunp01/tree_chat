# Tree Chat

A local, single-user chat client where every tangent becomes a branch anchored to the passage
that prompted it. Branches can be parked, resumed, and closed with a conclusion that is merged
back into an ancestor. The whole conversation is a visible, zoomable tree.

- What it does and why: `.claude/steering/requirements.md` and `.claude/steering/design.md`.
- How to build, run and test: `.claude/steering/tech.md`.

Quick start (Windows, needs uv and Node):

```bash
uv sync
cd web && npm ci && npm run build && cd ..
uv run treechat
```

Then open http://127.0.0.1:8765. Set `ANTHROPIC_API_KEY` for real replies, or
`TREECHAT_PROVIDER=fake` to run offline. Tests never call a real model: `uv run pytest`.
