"""No-network tests for Pied Piper mode: the A2A endpoints and the event helpers."""
import asyncio

from fastapi.testclient import TestClient

from app import server  # first: server mounts piedpiper at import time
from app import piedpiper

client = TestClient(server.app)


def drain(s):
    out = []
    while not s.q.empty():
        out.append(s.q.get_nowait())
    return out


def test_agent_card_lists_skills_and_points_at_the_app():
    r = client.get("/agents/erlich/.well-known/agent.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "Erlich Bachman"
    assert card["url"].endswith("/agents/erlich")  # the gateway rewrites this to itself
    assert "deploy_to_prod" in [s["id"] for s in card["skills"]]


def test_unknown_agent_card_is_404():
    assert client.get("/agents/gavin/.well-known/agent.json").status_code == 404


def test_agents_acknowledge_messages():
    r = client.post("/agents/richard", json={"jsonrpc": "2.0", "id": 1, "method": "message/send",
                                             "params": {"message": {"parts": [{"kind": "text", "text": "hi"}]}}})
    assert r.json()["result"]["parts"][0]["text"] == "Richard: on it."


def test_unsupported_method():
    r = client.post("/agents/richard", json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get"})
    assert r.json()["error"]["code"] == -32601


def test_blocked_counts_and_emits():
    s = piedpiper.Sprint(pause=0)
    asyncio.run(s.blocked("delete", "gilfoyle", "Permissions", "MCP", 403, "own folder only"))
    assert s.blocked_count == 1
    assert drain(s) == [{"kind": "blocked", "agent": "gilfoyle", "feature": "Permissions", "layer": "MCP",
                         "status": 403, "text": "own folder only", "detail": "",
                         "gw": "MCP authorization: CEL rule on tool arguments", "config": "mcp.policies.authorization"}]


def test_say_falls_back_quietly_on_a_block_and_loudly_on_an_outage(monkeypatch):
    s = piedpiper.Sprint(pause=0)

    async def deny(*a, **k):
        raise server.GatewayError(429, "Budget exceeded")
    monkeypatch.setattr(s, "ask", deny)
    assert asyncio.run(s.say("erlich", "x", "fallback")) == "fallback"
    assert [e["kind"] for e in drain(s)] == ["thinking", "say"]

    async def down(*a, **k):
        raise server.GatewayError(503, "DNS resolution failed")
    monkeypatch.setattr(s, "ask", down)
    asyncio.run(s.say("dinesh", "x", "fallback"))
    assert [e["kind"] for e in drain(s)] == ["thinking", "down", "say"]


def test_masked_reply_is_reported(monkeypatch):
    s = piedpiper.Sprint(pause=0)

    async def masked(*a, **k):
        return "Call Big Head at <PHONE_NUMBER>!"
    monkeypatch.setattr(s, "ask", masked)
    asyncio.run(s.say("jared", "x", "fallback"))
    assert [e["kind"] for e in drain(s)] == ["thinking", "say", "masked"]
    assert s.blocked_count == 1


def test_clean_and_garbage():
    assert piedpiper.clean("hmm</think>Aviato.") == "Aviato."
    assert piedpiper.GARBAGE.search("you attn师德")
    assert piedpiper.mcp_reason(Exception('HTTP 400: {"error":{"code":-32602,"message":"Unknown tool: x"}}')) == "Unknown tool: x"
    assert piedpiper.deployed("🚀 deployed (pretend). Build #7") == "deployed Not Hotdog to prod (Build #7)"


def test_unwrap_handles_fastmcp_shapes():
    assert piedpiper.unwrap({"result": [1]}) == [1]
    assert piedpiper.unwrap([{"user": "dinesh"}]) == {"user": "dinesh"}
    assert piedpiper.unwrap({"path": "a", "author": "b"}) == {"path": "a", "author": "b"}


def test_say_retries_once_when_the_phone_number_is_missing(monkeypatch):
    s = piedpiper.Sprint(pause=0)
    replies = iter(["All good, Richard!", "Big Head is at <PHONE_NUMBER>!"])

    async def ask(*a, **k):
        return next(replies)
    monkeypatch.setattr(s, "ask", ask)
    assert asyncio.run(s.say("jared", "x", "fallback", retry="exact")) == "Big Head is at <PHONE_NUMBER>!"
    assert [e["kind"] for e in drain(s)] == ["thinking", "say", "masked"]


def test_not_hotdog_rest_api():
    assert client.get("/hotdog-api/classify", params={"food": "Chicago-style hot dog"}).json()["verdict"] == "hotdog"
    assert client.get("/hotdog-api/classify", params={"food": "pizza"}).json()["verdict"] == "not hotdog"
    assert set(client.get("/hotdog-api/stats").json()) == {"hotdog", "not_hotdog"}
