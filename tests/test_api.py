"""HTTP API (Req 1-4, 8): routes, error shapes, SSE, read models. Fake provider only; no AI credits (Req 8.5)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from treechat.api.app import create_app
from treechat.api.state import State
from treechat.provider.fake import FakeProvider


def events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


class Api:
    def __init__(self, client: httpx.AsyncClient, state: State) -> None:
        self.c = client
        self.state = state
        self.provider: FakeProvider = state.provider  # type: ignore[assignment]

    async def new_tree(self, content: str = "How does prefix caching work?") -> tuple[str, str]:
        r = await self.c.post("/api/trees", json={"content": content})
        assert r.status_code == 201, r.text
        return r.json()["tree"]["id"], r.json()["message"]["id"]

    async def reply(self, user_id: str) -> dict[str, Any]:
        r = await self.c.post(f"/api/messages/{user_id}/reply")
        assert r.status_code == 200, r.text
        return events(r.text)[-1]

    async def send(self, tree: str, parent: str, content: str) -> str:
        r = await self.c.post(f"/api/trees/{tree}/messages", json={"parent_id": parent, "content": content})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def turn(self, tree: str, parent: str, content: str) -> tuple[str, str]:
        u = await self.send(tree, parent, content)
        done = await self.reply(u)
        assert done["type"] == "done", done
        return u, done["message"]["id"]


def assert_error(r: httpx.Response, status: int, category: str, *fields: str) -> None:
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"] == category and body["fields"] == list(fields) and body["message"]


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield Api(client, app.state.tc)


async def test_the_whole_flow_with_a_fork(api: Api) -> None:  # Req 1.1, 2.2, 3.1-3.4, 6
    tree, root = await api.new_tree()
    first = await api.reply(root)
    assert first["type"] == "done" and first["message"]["parent_id"] == root
    a1 = first["message"]["id"]
    u2, a2 = await api.turn(tree, a1, "And thinking blocks?")
    u3, a3 = await api.turn(tree, a1, "Go back: what about TTLs?")  # a new branch from a1

    t = (await api.c.get(f"/api/trees/{tree}")).json()
    assert t["title"] == "How does prefix caching work?"
    assert t["default_point"] == a3  # Req 2.2: the most recent Reply
    assert [(b["id"], b["parent_branch_id"], b["message_ids"]) for b in t["branches"]] == [
        (root, None, [root, a1]),
        (u2, root, [u2, a2]),
        (u3, root, [u3, a3]),
    ]
    assert t["branches"][2]["label"] == "Go back: what about TTLs?" and t["branches"][2]["forked_from"] == a1

    path = (await api.c.get(f"/api/messages/{a3}/path")).json()
    assert [m["id"] for m in path["messages"]] == [root, a1, u3, a3]  # Req 2.1: the other branch is not on it
    assert [m["child_count"] for m in path["messages"]] == [1, 2, 1, 0]  # Req 2.4: a1 has two children
    assert path["awaiting_reply"] is False and path["latest_below"] is None
    back = (await api.c.get(f"/api/messages/{a1}/path")).json()  # going back to a1
    assert [m["id"] for m in back["messages"]] == [root, a1] and back["latest_below"] == a3  # Req 2.4

    man = (await api.c.get(f"/api/messages/{a3}/manifest")).json()
    assert [e["id"] for e in man["entries"]] == [root, a1, u3]  # Req 4.1, 4.5
    assert_error(await api.c.get(f"/api/messages/{u3}/manifest"), 404, "not_found")

    listing = (await api.c.get("/api/trees")).json()
    assert [x["id"] for x in listing] == [tree]


async def test_trees_are_listed_by_activity_and_can_be_renamed(api: Api) -> None:  # Req 1.2-1.4
    t1, r1 = await api.new_tree("first")
    t2, _ = await api.new_tree("second")
    await api.reply(r1)  # t1 is now the most recently active
    assert [x["id"] for x in (await api.c.get("/api/trees")).json()] == [t1, t2]
    r = await api.c.patch(f"/api/trees/{t2}", json={"title": "  renamed  "})
    assert r.json()["title"] == "renamed"
    assert_error(await api.c.patch(f"/api/trees/{t2}", json={"title": " "}), 422, "validation", "title")
    assert_error(await api.c.patch(f"/api/trees/{t2}", json={"title": "x" * 201}), 422, "validation", "title")


async def test_validation_and_conflict_errors(api: Api) -> None:  # Req 3.2, 3.9
    tree, root = await api.new_tree()
    other, oroot = await api.new_tree("other")
    a1 = (await api.reply(root))["message"]["id"]
    oa = (await api.reply(oroot))["message"]["id"]
    c = api.c
    assert_error(await c.post("/api/trees", json={"content": "  "}), 422, "validation", "content")
    assert_error(await c.post("/api/trees", json={}), 422, "validation", "content")
    assert_error(
        await c.post(f"/api/trees/{tree}/messages", json={"parent_id": a1, "content": ""}), 422, "validation", "content"
    )
    assert_error(
        await c.post(f"/api/trees/{tree}/messages", json={"parent_id": a1, "content": "x" * 100_001}),
        422,
        "validation",
        "content",
    )
    assert_error(await c.post(f"/api/trees/{tree}/messages", json={"content": "x"}), 422, "validation", "parent_id")
    assert_error(await c.post(f"/api/trees/{tree}/messages", json={"parent_id": root, "content": "x"}), 409, "conflict")
    assert_error(await c.post(f"/api/trees/{tree}/messages", json={"parent_id": oa, "content": "x"}), 409, "conflict")
    assert_error(await c.post(f"/api/messages/{root}/reply"), 409, "conflict")  # already answered
    assert_error(await c.post(f"/api/messages/{a1}/reply"), 409, "conflict")  # not a question
    assert len((await c.get(f"/api/messages/{a1}/path")).json()["messages"]) == 2  # nothing was added
    assert other


async def test_not_found_everywhere(api: Api) -> None:
    for method, path, body in [
        ("GET", "/api/trees/nope", None),
        ("PATCH", "/api/trees/nope", {"title": "t"}),
        ("POST", "/api/trees/nope/messages", {"parent_id": "x", "content": "c"}),
        ("GET", "/api/messages/nope/path", None),
        ("POST", "/api/messages/nope/reply", None),
        ("GET", "/api/messages/nope/live", None),
        ("GET", "/api/messages/nope/manifest", None),
    ]:
        assert_error(await api.c.request(method, path, json=body), 404, "not_found")


@pytest.mark.parametrize(
    ("outcome", "category"), [("fail", "provider_error"), ("refuse", "refused"), ("too_large", "context_too_large")]
)
async def test_a_failed_reply_keeps_the_question(api: Api, outcome: str, category: str) -> None:  # Req 3.5, 3.10, 4.6
    tree, root = await api.new_tree()
    api.provider.then(outcome)
    err = await api.reply(root)
    assert err["type"] == "error" and err["error"] == category
    path = (await api.c.get(f"/api/messages/{root}/path")).json()
    assert path["awaiting_reply"] is True and [m["id"] for m in path["messages"]] == [root]
    assert (await api.c.get(f"/api/trees/{tree}")).json()["default_point"] == root
    assert (await api.reply(root))["type"] == "done"  # requested again


async def test_provider_unavailable_and_cut_off(api: Api) -> None:  # Req 3.6, 8.3
    tree, root = await api.new_tree()
    api.provider.available = False
    err = await api.reply(root)
    assert err["error"] == "provider_unavailable" and "ANTHROPIC_API_KEY" in err["message"]
    assert (await api.c.get(f"/api/trees/{tree}")).status_code == 200  # still serves
    api.provider.available = True
    api.provider.then("truncate")
    assert (await api.reply(root))["message"]["cut_off"] is True


async def test_busy_then_disconnect_then_live(api: Api) -> None:  # Req 3.7, 3.8
    _, root = await api.new_tree()
    _, other = await api.new_tree("another")
    gate = asyncio.Event()
    api.provider.gate = gate
    try:
        await _busy_then_live(api, gate, root, other)
    finally:
        gate.set()  # a failing assertion must not leave the job (and the fixture's drain) waiting forever


async def _busy_then_live(api: Api, gate: asyncio.Event, root: str, other: str) -> None:
    first = asyncio.create_task(api.c.post(f"/api/messages/{root}/reply"))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if api.state.registry.is_busy(root):
            break
    assert_error(await api.c.post(f"/api/messages/{root}/reply"), 409, "busy")
    assert (await api.c.get(f"/api/messages/{root}/path")).json()["reply_in_progress"] is True
    first.cancel()  # the browser goes away
    await asyncio.gather(first, return_exceptions=True)
    assert api.state.registry.is_busy(root)  # the job carries on
    live = asyncio.create_task(api.c.get(f"/api/messages/{root}/live"))
    other_reply = asyncio.create_task(api.c.post(f"/api/messages/{other}/reply"))  # unaffected
    await asyncio.sleep(0.05)
    gate.set()
    evs = events((await live).text)
    assert evs[0]["type"] == "started" and evs[-1]["type"] == "done"
    assert events((await other_reply).text)[-1]["type"] == "done"
    path = (await api.c.get(f"/api/messages/{evs[-1]['message']['id']}/path")).json()
    assert path["messages"][-1]["role"] == "assistant"  # persisted anyway
    assert (await api.c.get(f"/api/messages/{root}/live")).status_code == 204


async def test_there_is_no_way_to_edit_or_delete(api: Api) -> None:  # Req 5.2
    tree, root = await api.new_tree()
    for method, path in [
        ("DELETE", f"/api/trees/{tree}"),
        ("DELETE", f"/api/messages/{root}"),
        ("PATCH", f"/api/messages/{root}"),
        ("PUT", f"/api/messages/{root}"),
    ]:
        assert (await api.c.request(method, path)).status_code in (404, 405)
