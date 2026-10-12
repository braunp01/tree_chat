# Tree Chat

A local, single-user chat client that works like an ordinary chat, except that a conversation is a tree.
Go back to any earlier reply and send from there: that starts a new branch and leaves everything else as it
was. A graph of the tree sits beside the chat. Nothing is ever edited, regenerated or deleted, and the model
sees exactly the conversation on screen.

- What it does and why: `.claude/steering/requirements.md` and `.claude/steering/design.md`.
- How to build, run and test: `.claude/steering/tech.md`.

Quick start (Windows PowerShell, needs uv and Node):

```powershell
uv sync
cd web; npm ci; npm run build; cd ..
uv run treechat
```

Then open http://127.0.0.1:8765. Set `ANTHROPIC_API_KEY` for real replies, or run offline with the fake
provider: `$env:TREECHAT_PROVIDER="fake"; uv run treechat` (in cmd: `set TREECHAT_PROVIDER=fake` first).
Tests never call a real model: `uv run pytest`.
