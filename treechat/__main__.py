"""`uv run treechat`: serve the API and built front end on 127.0.0.1 only (design.md, Network exposure)."""

from __future__ import annotations

import argparse

import uvicorn

from treechat.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="treechat")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    args = parser.parse_args()
    cfg = load_config()
    uvicorn.run(
        "treechat.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=cfg.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
