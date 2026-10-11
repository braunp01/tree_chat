"""HTTP API (step 6): routes, error shapes, SSE, read models. Fake provider only; no AI credits (Req 17.5)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from treechat.api.app import create_app
from treechat.api.state import State
from treechat.domain import rules
from treechat.provider.fake import FakeProvider
from treechat.store import repo


class Api:
    def __init__(self, client: httpx.AsyncClient, state: State) -> None:
        self.c = client
        self.state = state
        self.provider: FakeProvider = state.provider  # type: ignore[assignment]

    async def drain(self) -> None:
        await self.state.registry.drain()

    async def tree(self) -> tuple[str, str]:
        r = await self.c.post("/api/trees")
        assert r.status_code == 201
        return r.json()["id"], r.json()["trunk_branch_id"]

    async def send(self, branch: str, content: str) -> dict[str, Any]:
        r = await self.c.post(f"/api/branches/{branch}/messages", json={"content": content})
        assert r.status_code == 201, r.text
        return r.json()

    async def reply(self, branch: str) -> list[dict[str, Any]]:
        r = await self.c.post(f"/api/branches/{branch}/reply")
        assert r.status_code == 200, r.text
        return events(r.text)

    async def chat(self, branch: str, content: str) -> dict[str, Any]:
        """Send and get the reply; returns the assistant Message."""
        await self.send(branch, content)
        evs = await self.reply(branch)
        assert evs[-1]["type"] == "done", evs
        return evs[-1]["message"]

    async def spawn(self, message: dict[str, Any], start: int, end: int, **kw: Any) -> dict[str, Any]:
        body = {
            "anchor": {
                "message_id": message["id"],
                "start": start,
                "end": end,
                "quoted_text": message["content"][start:end],
            },
            **kw,
        }
        r = await self.c.post("/api/branches", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    async def view(self, branch: str) -> dict[str, Any]:
        r = await self.c.get(f"/api/branches/{branch}/view")
        assert r.status_code == 200, r.text
        return r.json()


def events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def assert_error(r: httpx.Response, status: int, category: str, *fields: str) -> None:
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"] == category
    assert body["fields"] == list(fields)
    assert isinstance(body["message"], str) and body["message"]


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield Api(client, app.state.tc)


# --- The whole flow (Req 1-2, 4, 12, 13) ----------------------------------------------------------


async def test_send_reply_spawn_close_and_merge(api: Api) -> None:
    tree_id, trunk = await api.tree()
    first = await api.send(trunk, "Explain prefix caching in detail please")
    assert (await api.c.get("/api/trees")).json()[0]["title"] == "Explain prefix caching in detail please"  # Req 1.3
    evs = await api.reply(trunk)
    assert [e["type"] for e in evs][0] == "started" and evs[-1]["type"] == "done"
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == evs[-1]["message"]["content"]
    answer = evs[-1]["message"]
    assert answer["role"] == "assistant" and answer["parent_message_id"] == first["id"]

    # Spawn (parked, no intent): returns at once, the Generated_Intent arrives in the background (Req 4.9).
    t = await api.spawn(answer, 0, 10)
    assert t["status"] == "parked" and t["parent_branch_id"] == trunk and t["depth"] == 1
    assert t["intent"] is None and t["generated_intent"] is None
    await api.drain()
    assert (await api.view(t["id"]))["branch"]["generated_intent"].startswith("Fake summary")
    assert (await api.c.get(f"/api/trees/{tree_id}/queue")).json()[0]["id"] == t["id"]

    # Sending in a parked tangent opens it (Req 2.8); the framing is fixed with its first message (Req 7.3).
    reply_in_t = await api.chat(t["id"], "What about the cache?")
    v = await api.view(t["id"])
    assert v["branch"]["status"] == "open" and v["framing"]["frozen"] is True
    assert v["inherited"]["message_count"] == 2 and v["inherited"]["anchor_message_id"] == answer["id"]
    assert [m["role"] for m in v["messages"]] == ["user", "assistant"]
    assert v["assistant_reply_count"] == 1 and v["awaiting_reply"] is False
    assert [m["id"] for m in v["merge_targets"]] == [trunk]

    # The reply's manifest is inspectable (Req 7.8).
    man = (await api.c.get(f"/api/messages/{reply_in_t['id']}/manifest")).json()
    assert man["model"] == api.state.ctx.settings.model and any(e["kind"] == "framing" for e in man["entries"])
    assert (await api.c.get(f"/api/messages/{first['id']}/manifest")).status_code == 404

    # Draft, then close and merge (Req 12.1, 13.1).
    draft = (await api.c.post(f"/api/branches/{t['id']}/conclusion-draft")).json()["text"]
    assert draft.startswith("Fake summary")
    r = await api.c.post(f"/api/branches/{t['id']}/close", json={"outcome": "merged", "conclusion": draft})
    assert r.status_code == 200, r.text
    closed = r.json()
    assert closed["status"] == "closed" and closed["closings"][0]["merge_target"] == trunk
    note_id = closed["note_message_id"]
    trunk_view = await api.view(trunk)
    note = trunk_view["messages"][-1]
    assert note["id"] == note_id and note["role"] == "note" and note["source"]["branch_id"] == t["id"]  # Req 13.7
    assert (await api.c.get(f"/api/messages/{note_id}/preview")).json()["preview"].startswith("<tree_chat_note")

    # Closed: no more messages (Req 12.8); reopen keeps the record (Req 12.7).
    assert_error(await api.c.post(f"/api/branches/{t['id']}/messages", json={"content": "more"}), 409, "conflict")
    reopened = (await api.c.post(f"/api/branches/{t['id']}/reopen")).json()
    assert reopened["status"] == "open" and len(reopened["closings"]) == 1


async def test_park_and_resume_and_generated_standing(api: Api) -> None:
    tree_id, trunk = await api.tree()
    answer = await api.chat(trunk, "hello there")
    t = await api.spawn(answer, 0, 5, intent="  my intent ", status="open")
    assert t["intent"] == "my intent" and t["status"] == "open"
    await api.drain()
    assert api.provider.completions == []  # an Intent was given: nothing to generate (Req 4.9)
    await api.chat(t["id"], "go on")
    parked = (await api.c.post(f"/api/branches/{t['id']}/park")).json()
    assert parked["status"] == "parked" and parked["parked_at"]
    await api.drain()
    item = (await api.c.get(f"/api/trees/{tree_id}/queue")).json()[0]
    assert item["standing"].startswith("Fake summary") and item["parent_label"] == "Trunk"  # Req 11.2
    assert (await api.c.post(f"/api/branches/{t['id']}/resume")).json()["status"] == "open"
    assert_error(await api.c.post(f"/api/branches/{t['id']}/resume"), 409, "conflict")  # Req 10.1


# --- Errors: shape and field names ----------------------------------------------------------------


async def test_validation_errors_name_the_field(api: Api) -> None:
    tree_id, trunk = await api.tree()
    answer = await api.chat(trunk, "some text to anchor on")
    c = api.c
    assert_error(await c.patch(f"/api/trees/{tree_id}", json={"title": "  "}), 422, "validation", "title")  # Req 1.4
    assert_error(await c.patch(f"/api/trees/{tree_id}", json={"title": "x" * 201}), 422, "validation", "title")
    assert_error(await c.post(f"/api/branches/{trunk}/messages", json={"content": "  "}), 422, "validation", "content")
    assert_error(await c.post(f"/api/branches/{trunk}/messages", json={}), 422, "validation", "content")  # Req 2.7
    a = {"message_id": answer["id"], "start": 0, "end": 4, "quoted_text": answer["content"][:4]}
    spawn = "/api/branches"
    assert_error(await c.post(spawn, json={"anchor": {**a, "quoted_text": "nope"}}), 422, "validation", "anchor")
    assert_error(await c.post(spawn, json={"anchor": {**a, "end": 9999}}), 422, "validation", "anchor")  # Req 4.5
    assert_error(await c.post(spawn, json={"anchor": {**a, "start": 4, "end": 4}}), 422, "validation", "anchor")
    assert_error(await c.post(spawn, json={"anchor": {**a, "start": "x"}}), 422, "validation", "anchor")
    assert_error(await c.post(spawn, json={"anchor": a, "intent": "i" * 201}), 422, "validation", "intent")  # Req 4.3
    assert_error(await c.post(spawn, json={"anchor": a, "status": "closed"}), 422, "validation", "status")
    assert_error(await c.post(spawn, json={"anchor": a, "fork_at": "never"}), 422, "validation", "fork_point")
    assert_error(await c.post(spawn, json={}), 422, "validation", "anchor")
    t = await api.spawn(answer, 0, 4)
    tid = t["id"]
    await api.chat(tid, "hi")
    close = f"/api/branches/{tid}/close"
    assert_error(await c.post(close, json={"outcome": "merged", "conclusion": " "}), 422, "validation", "conclusion")
    assert_error(await c.post(close, json={"outcome": "kept"}), 422, "validation", "conclusion")  # Req 12.2
    assert_error(
        await c.post(close, json={"outcome": "kept", "conclusion": "c" * 2001}), 422, "validation", "conclusion"
    )
    assert_error(await c.post(close, json={"outcome": "sideways", "conclusion": "c"}), 422, "validation", "outcome")
    assert_error(
        await c.post(close, json={"outcome": "merged", "conclusion": "c", "merge_target": tid}),
        422,
        "validation",
        "merge_target",
    )
    assert_error(await c.post(close, json={"conclusion": "c"}), 422, "validation", "outcome")
    assert_error(
        await c.patch(f"/api/branches/{tid}", json={"fork_at": "tip"}), 422, "validation", "fork_point"
    )  # Req 9.3
    assert_error(await c.get(f"/api/trees/{tree_id}/queue?order=sideways"), 422, "validation", "order")
    # Nothing above changed the Tree (Req 16.5).
    assert (await api.view(tid))["branch"]["status"] == "open" and (await api.view(tid))["branch"]["closings"] == []


async def test_not_found_and_conflict_shapes(api: Api) -> None:
    c = api.c
    for method, path in [
        ("GET", "/api/trees/nope"),
        ("GET", "/api/trees/nope/map"),
        ("GET", "/api/trees/nope/queue"),
        ("PATCH", "/api/trees/nope"),
        ("GET", "/api/branches/nope/view"),
        ("GET", "/api/branches/nope/live"),
        ("POST", "/api/branches/nope/messages"),
        ("POST", "/api/branches/nope/reply"),
        ("POST", "/api/branches/nope/park"),
        ("POST", "/api/branches/nope/resume"),
        ("POST", "/api/branches/nope/reopen"),
        ("POST", "/api/branches/nope/conclusion-draft"),
        ("POST", "/api/branches/nope/close"),
        ("POST", "/api/messages/nope/alternatives"),
        ("GET", "/api/messages/nope/manifest"),
        ("GET", "/api/messages/nope/preview"),
    ]:
        body = {"title": "t", "content": "c", "outcome": "kept", "conclusion": "c"}
        r = await c.request(method, path, json=body if method != "GET" else None)
        assert_error(r, 404, "not_found")
    assert_error(
        await c.post(
            "/api/branches", json={"anchor": {"message_id": "nope", "start": 0, "end": 1, "quoted_text": "a"}}
        ),
        404,
        "not_found",
    )
    _, trunk = await api.tree()
    assert_error(await c.post(f"/api/branches/{trunk}/park"), 409, "conflict")  # the Trunk never moves
    assert_error(
        await c.post(f"/api/branches/{trunk}/close", json={"outcome": "abandoned"}), 409, "conflict"
    )  # Req 12.9
    assert_error(await c.post(f"/api/branches/{trunk}/reply"), 409, "conflict")  # nothing to reply to


async def test_message_errors_conflict(api: Api) -> None:
    _, trunk = await api.tree()
    first = await api.send(trunk, "hello")
    assert_error(
        await api.c.post(f"/api/branches/{trunk}/messages", json={"content": "again"}), 409, "conflict"
    )  # Req 2.9
    evs = await api.reply(trunk)
    note_source = evs[-1]["message"]
    t = await api.spawn(note_source, 0, 4)
    await api.chat(t["id"], "q")
    await api.c.post(f"/api/branches/{t['id']}/close", json={"outcome": "merged", "conclusion": "done"})
    note = (await api.view(trunk))["messages"][-1]
    assert_error(await api.c.post(f"/api/messages/{note['id']}/alternatives", json={"content": "x"}), 409, "conflict")
    assert_error(await api.c.post(f"/api/messages/{first['id']}/alternatives", json={}), 422, "validation", "content")


# --- Replies: failures, busy, disconnect (Req 2.3-2.6) --------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "category"), [("fail", "provider_error"), ("refuse", "refused"), ("too_large", "context_too_large")]
)
async def test_failed_reply_keeps_user_message_and_can_be_retried(api: Api, outcome: str, category: str) -> None:
    _, trunk = await api.tree()
    await api.send(trunk, "hello")
    api.provider.then(outcome)
    evs = await api.reply(trunk)
    assert evs[-1]["type"] == "error" and evs[-1]["error"] == category and evs[-1]["message"]
    v = await api.view(trunk)
    assert [m["role"] for m in v["messages"]] == ["user"] and v["awaiting_reply"] is True  # Req 2.3
    assert (await api.reply(trunk))[-1]["type"] == "done"  # asked again


async def test_provider_unavailable_is_an_error_event_and_the_app_still_serves(api: Api) -> None:
    tree_id, trunk = await api.tree()
    await api.send(trunk, "hello")
    api.provider.available = False
    evs = await api.reply(trunk)
    assert evs[-1]["error"] == "provider_unavailable" and "ANTHROPIC_API_KEY" in evs[-1]["message"]  # Req 17.3
    assert (await api.c.get(f"/api/trees/{tree_id}")).status_code == 200


async def test_truncated_reply_is_flagged(api: Api) -> None:
    _, trunk = await api.tree()
    await api.send(trunk, "hello")
    api.provider.then("truncate")
    done = (await api.reply(trunk))[-1]["message"]
    assert done["cut_off"] is True and done["stop_reason"] == "max_tokens"  # Req 2.4


async def test_busy_then_disconnect_then_live(api: Api) -> None:
    _, trunk = await api.tree()
    await api.send(trunk, "hello")
    gate = asyncio.Event()
    api.provider.gate = gate
    first = asyncio.create_task(api.c.post(f"/api/branches/{trunk}/reply"))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if api.state.registry.is_busy(trunk):
            break
    assert api.state.registry.is_busy(trunk)
    assert_error(await api.c.post(f"/api/branches/{trunk}/reply"), 409, "busy")  # Req 2.5
    assert_error(await api.c.post(f"/api/branches/{trunk}/messages", json={"content": "x"}), 409, "busy")
    first.cancel()  # the browser goes away
    await asyncio.gather(first, return_exceptions=True)
    assert api.state.registry.is_busy(trunk)  # Req 2.6: the job carries on
    live = asyncio.create_task(api.c.get(f"/api/branches/{trunk}/live"))
    await asyncio.sleep(0.05)
    gate.set()
    r = await live
    assert r.status_code == 200
    evs = events(r.text)
    assert evs[0]["type"] == "started" and evs[-1]["type"] == "done"
    assert (await api.view(trunk))["messages"][-1]["id"] == evs[-1]["message"]["id"]  # persisted anyway
    assert (await api.c.get(f"/api/branches/{trunk}/live")).status_code == 204  # nothing in progress now
    other = (await api.tree())[1]
    assert not api.state.registry.is_busy(other)  # other Branches are unaffected


# --- Alternatives (Req 3) and Fork_Point (Req 9) --------------------------------------------------


async def test_edit_and_regenerate_make_alternatives(api: Api) -> None:
    _, trunk = await api.tree()
    user = await api.send(trunk, "original question")
    answer = (await api.reply(trunk))[-1]["message"]

    r = await api.c.post(f"/api/messages/{user['id']}/alternatives", json={"content": "edited question"})
    assert r.status_code == 201
    edit = r.json()
    assert edit["kind"] == "alternative" and edit["parent_branch_id"] == trunk and edit["message_count"] == 1
    assert (await api.reply(edit["id"]))[-1]["type"] == "done"

    regen = (await api.c.post(f"/api/messages/{answer['id']}/alternatives")).json()
    assert regen["message_count"] == 0
    assert (await api.reply(regen["id"]))[-1]["type"] == "done"

    v = await api.view(trunk)
    assert [len(m["alternatives"]) for m in v["messages"]] == [1, 1]  # Req 3.4; the originals stay put
    assert [m["content"] for m in v["messages"]][0] == "original question"
    assert (await api.view(edit["id"]))["framing"]["anchor_quote"] == "original question"
    assert (
        await api.c.post(f"/api/branches/{edit['id']}/close", json={"outcome": "merged", "conclusion": "c"})
    ).status_code == 422


async def test_fork_point_can_move_until_the_first_message(api: Api) -> None:
    _, trunk = await api.tree()
    answer = await api.chat(trunk, "first")
    await api.chat(trunk, "second")
    t = await api.spawn(answer, 0, 3)
    assert t["fork_point_message_id"] == answer["id"]
    tip = (await api.view(trunk))["tip_message_id"]
    moved = (await api.c.patch(f"/api/branches/{t['id']}", json={"fork_at": "tip"})).json()
    assert moved["fork_point_message_id"] == tip and moved["parent_messages_since_fork"] == 0  # Req 9.2
    relabelled = (await api.c.patch(f"/api/branches/{t['id']}", json={"intent": "new"})).json()
    assert relabelled["intent"] == "new"
    cleared = (await api.c.patch(f"/api/branches/{t['id']}", json={"intent": None})).json()
    assert cleared["intent"] is None
    await api.chat(t["id"], "go")
    assert_error(
        await api.c.patch(f"/api/branches/{t['id']}", json={"fork_at": "anchor"}), 422, "validation", "fork_point"
    )


# --- Read models on a seeded tree -----------------------------------------------------------------


async def seeded(api: Api) -> dict[str, Any]:
    """Trunk with two exchanges; tangent A on the first reply (with a grandchild and an Alternative); tangent B."""
    tree_id, trunk = await api.tree()
    r1 = await api.chat(trunk, "first question")
    r2 = await api.chat(trunk, "second question")
    a = await api.spawn(r1, 0, 4, intent="A")
    b = await api.spawn(r2, 2, 8, intent="B", fork_at="tip")
    ra = await api.chat(a["id"], "in A")
    g = await api.spawn(ra, 1, 3, intent="G", status="open")
    await api.chat(g["id"], "in G")
    alt = (await api.c.post(f"/api/messages/{r1['id']}/alternatives")).json()
    await api.reply(alt["id"])
    return {"tree": tree_id, "trunk": trunk, "r1": r1, "r2": r2, "a": a, "b": b, "g": g, "alt": alt}


async def test_tree_and_outline_data(api: Api) -> None:
    s = await seeded(api)
    listing = (await api.c.get("/api/trees")).json()
    assert listing[0]["open_count"] == 3 and listing[0]["parked_count"] == 1  # A and G open (alt too), B parked
    tree = (await api.c.get(f"/api/trees/{s['tree']}")).json()
    by_id = {b["id"]: b for b in tree["branches"]}
    assert {k: by_id[s[k]["id"]]["depth"] for k in ("a", "b", "g")} == {"a": 1, "b": 1, "g": 2}
    assert by_id[s["trunk"]]["kind"] == "trunk" and by_id[s["trunk"]]["depth"] == 0
    assert by_id[s["g"]["id"]]["parent_branch_id"] == s["a"]["id"]


async def test_listing_counts_after_opening(api: Api) -> None:
    s = await seeded(api)
    by_status: dict[str, int] = {}
    for b in (await api.c.get(f"/api/trees/{s['tree']}")).json()["branches"]:
        if b["kind"] != "trunk":
            by_status[b["status"]] = by_status.get(b["status"], 0) + 1
    listing = (await api.c.get("/api/trees")).json()[0]
    assert (listing["open_count"], listing["parked_count"]) == (by_status.get("open", 0), by_status.get("parked", 0))


async def test_path_view_markers_and_inherited_prefix(api: Api) -> None:
    s = await seeded(api)
    trunk_view = await api.view(s["trunk"])
    msgs = trunk_view["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    marker_a = msgs[1]["markers"][0]
    assert (marker_a["branch_id"], marker_a["start"], marker_a["end"], marker_a["status"]) == (
        s["a"]["id"],
        0,
        4,
        "open",
    )
    assert msgs[3]["markers"][0]["intent"] == "B" and msgs[3]["markers"][0]["status"] == "parked"  # Req 5.1
    gv = await api.view(s["g"]["id"])
    assert gv["inherited"]["anchor_message_id"] == s["g"]["anchor"]["message_id"]
    assert [b["id"] for b in gv["breadcrumb"]] == [s["trunk"], s["a"]["id"]]  # Req 14.3
    kinds = [e["kind"] for e in gv["inherited"]["entries"]]
    assert kinds == ["message", "message", "message", "framing", "message"]  # trunk to r1, then A's framing (Req 7.1)
    assert gv["inherited"]["message_count"] == kinds.count("message")
    # Markers appear in the inherited part too (Req 5.1).
    inherited_ids = {e["message"]["id"]: e["message"] for e in gv["inherited"]["entries"] if e["kind"] == "message"}
    assert inherited_ids[s["r1"]["id"]]["markers"][0]["branch_id"] == s["a"]["id"]


async def test_queue_orderings_and_staleness(api: Api) -> None:
    tree_id, trunk = await api.tree()
    r1 = await api.chat(trunk, "one")
    first = await api.spawn(r1, 0, 3, intent="first")
    second = await api.spawn(r1, 0, 3, intent="second")
    await api.chat(trunk, "two")  # the parent moves on past the fork point
    q = lambda order: api.c.get(f"/api/trees/{tree_id}/queue", params={"order": order})  # noqa: E731
    assert [x["id"] for x in (await q("oldest")).json()] == [first["id"], second["id"]]
    assert [x["id"] for x in (await q("newest")).json()] == [second["id"], first["id"]]
    assert [x["id"] for x in (await q("parent")).json()] == [first["id"], second["id"]]
    item = (await q("oldest")).json()[0]
    assert (
        item["parent_messages_since_fork"] == 2
        and item["parked_at"]
        and item["anchor"]["quoted_text"] == r1["content"][:3]
    )  # Req 10.5
    await api.c.post(f"/api/branches/{first['id']}/resume")
    assert [x["id"] for x in (await q("oldest")).json()] == [second["id"]]


async def test_map_positions_match_the_domain(api: Api) -> None:
    s = await seeded(api)
    m = (await api.c.get(f"/api/trees/{s['tree']}/map")).json()
    with api.state.ctx.store.read() as c:
        snap = repo.load_snapshot(c, s["tree"])
    assert len(m["branches"]) == len(snap.branches)
    assert sum(b["message_count"] for b in m["branches"]) == len(snap.messages)
    for b in m["branches"]:
        assert "content" not in json.dumps(b)  # structure only (Req 14.8)
        for msg in b["messages"]:
            assert msg["position"] == rules.conversation_position(snap, msg["id"])
        if b["anchor_message_id"]:
            assert b["anchor_position"] == rules.conversation_position(snap, b["anchor_message_id"])  # Req 14.9
        if b["messages"]:
            assert b["start_position"] == b["messages"][0]["position"]
    empty = next(b for b in m["branches"] if b["id"] == s["b"]["id"])
    assert empty["message_count"] == 0 and empty["start_position"] == 4  # forked at the tip: after 4 messages


async def test_conclusion_draft_without_credentials_is_empty(api: Api) -> None:
    _, trunk = await api.tree()
    answer = await api.chat(trunk, "hello world")
    t = await api.spawn(answer, 0, 5)
    api.provider.available = False
    r = await api.c.post(f"/api/branches/{t['id']}/conclusion-draft")
    assert r.status_code == 200 and r.json() == {"text": ""}
    api.provider.available = True
    api.provider.then("fail_complete")
    assert_error(await api.c.post(f"/api/branches/{t['id']}/conclusion-draft"), 502, "provider_error")


async def test_close_with_abandoned_descendants(api: Api) -> None:
    s = await seeded(api)
    r = await api.c.post(
        f"/api/branches/{s['a']['id']}/close", json={"outcome": "kept", "conclusion": "k", "abandon_descendants": True}
    )
    assert r.status_code == 200 and r.json()["abandoned_branch_ids"] == [s["g"]["id"]]  # Req 12.6
    assert (await api.view(s["g"]["id"]))["branch"]["closings"][0]["outcome"] == "abandoned"


async def test_nothing_is_exposed_beyond_the_contract(api: Api) -> None:
    for method, path in [("DELETE", "/api/trees/x"), ("DELETE", "/api/branches/x"), ("DELETE", "/api/messages/x")]:
        assert (await api.c.request(method, path)).status_code in (404, 405)  # Req 16.3: no deletion
