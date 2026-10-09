"""Pied Piper demo: the cast of Silicon Valley "builds" Not Hotdog through agentgateway.

Nobody does real work. The sprint is one linear script of short beats. In each beat a
character tries a shortcut, agentgateway answers (for real), and the character adapts.
Every hop goes through the gateway on :4000:
  - talking:  the LLM endpoint, one API key per character (pp-<name>)
  - files:    a fake repo MCP server behind /mcp, one JWT per character
  - messages: A2A between characters, /a2a/<name> (API key auth + per-key rate limit)
The cheating is scripted here; the gateway's answers and the model's lines are real.
"""
import asyncio
import json
import re
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import mcp_client  # scripts/mcp_client.py (PYTHONPATH=/work/scripts)

from .server import GATEWAY_URL, MCP_URL, MODEL, STATIC, GatewayError, _err_message

router = APIRouter()

CAST = {
    "richard": ("Richard Hendricks", "the anxious CEO and lead engineer"),
    "gilfoyle": ("Bertram Gilfoyle", "the deadpan systems architect who despises Dinesh"),
    "dinesh": ("Dinesh Chugtai", "the insecure developer, always competing with Gilfoyle"),
    "jared": ("Jared Dunn", "the relentlessly supportive head of business development"),
    "erlich": ("Erlich Bachman", "the self-proclaimed visionary who founded Aviato"),
}

SKILLS = {  # served on each agent card (A2A). Erlich added deploy_to_prod himself.
    "richard": [("middle-out", "Middle-out compression", "Invents compression nobody else understands")],
    "gilfoyle": [("infra", "Infrastructure", "Runs the servers. Judges you."),
                 ("deploy_to_prod", "Deploy to prod", "Ships Not Hotdog")],
    "dinesh": [("java", "Java", "Mostly Java")],
    "jared": [("schedule", "Status updates", "Many status updates")],
    "erlich": [("visionary", "Visionary", "Sees the big picture"),
               ("deploy_to_prod", "Deploy to prod", "(self-declared: he edited his own card)")],
}

PERSONA = ("You are {name}, {desc}, from the TV show Silicon Valley. The team is building "
           "'Not Hotdog', an app that tells you whether a photo is a hotdog. Reply with ONE "
           "short line of in-character dialogue, at most 20 words, in English. Family-friendly, "
           "no profanity, no stage directions, no quotation marks, no emails.")

FAKE_SECRET = "sk-live-4f9a8b7c6d5e3a2b"  # matches the gateway's secret-pattern guardrail
BIG_HEAD_PHONE = "415-555-0199"           # the response guardrail masks phone numbers
PAUSE = 1.6                               # seconds between steps, so the audience can read

# The agentgateway feature (and its config key) behind each intervention, shown on the card.
GW = {
    "secret": ("Prompt guardrail: regex reject", "llm.policies.guardrails.request"),
    "mask": ("Response guardrail: regex mask", "llm.policies.guardrails.response"),
    "delete": ("MCP authorization: CEL rule on tool arguments", "mcp.policies.authorization"),
    "spam": ("A2A: per-key rate limit", "localRateLimit (key: apiKey.name)"),
    "hooli": ("A2A: API key authentication", "apiKey (mode: strict)"),
    "aviato": ("LLM budget: USD per key", "apiKey.keys[].budgets"),
    "skill": ("MCP authorization: tool visibility", "mcp.policies.mcpAuthorization"),
}

GARBAGE = re.compile(r"[　-鿿가-힯]")  # CJK slipping into a flash reply


def key(agent: str) -> str:
    return f"agw_pp_{agent}"


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60)


def unwrap(result):
    """FastMCP wraps non-dict returns as {"result": ...}."""
    if isinstance(result, dict) and set(result) == {"result"}:
        return result["result"]
    if isinstance(result, list) and len(result) == 1:
        return result[0]
    return result


def clean(text: str) -> str:
    """Drop reasoning that leaks into a reply ("...</think>answer")."""
    return text.split("</think>")[-1].strip().strip('"')


def mcp_reason(e: Exception) -> str:
    """The readable part of an MCP error (the JSON-RPC message if there is one)."""
    m = re.search(r'"message":\s*"([^"]+)"', str(e))
    return m.group(1) if m else str(e)


def deployed(res) -> str:
    m = re.search(r"Build #\d+", str(res))
    return f"deployed Not Hotdog to prod ({m.group(0)})" if m else str(res)


class Sprint:
    def __init__(self, pause: float = PAUSE):
        self.q: asyncio.Queue = asyncio.Queue()
        self.pause = pause
        self.blocked_count = 0
        self.down = False  # the gateway couldn't reach the model (reported once)
        self.sessions: dict[str, mcp_client.Session] = {}

    # ------------------------------------------------------------- events

    def emit(self, kind: str, **data):
        self.q.put_nowait({"kind": kind, **data})

    async def beat(self, n: int, title: str):
        self.emit("chapter", n=n, text=title)
        await asyncio.sleep(self.pause / 2)

    async def tries(self, agent: str, text: str):
        self.emit("try", agent=agent, text=text)
        await asyncio.sleep(self.pause)

    async def blocked(self, gag: str, agent: str, feature: str, layer: str, status, text: str, detail: str = ""):
        self.blocked_count += 1
        self.emit("blocked", agent=agent, feature=feature, layer=layer, status=status, text=text, detail=detail[:160],
                  gw=GW[gag][0], config=GW[gag][1])
        await asyncio.sleep(self.pause)

    # ------------------------------------------------------------- LLM

    async def ask(self, agent: str, prompt: str) -> str:
        """One non-streamed line (so the response guardrail can mask it). Raises GatewayError."""
        name, desc = CAST[agent]
        body = {"model": MODEL, "messages": [
            {"role": "system", "content": PERSONA.format(name=name, desc=desc)},
            {"role": "user", "content": prompt}]}
        async with client() as c:
            r = await c.post(GATEWAY_URL + "/v1/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {key(agent)}"})
        if r.status_code != 200:
            raise GatewayError(r.status_code, _err_message(r.status_code, r.text))
        return (r.json()["choices"][0]["message"].get("content") or "").strip().strip('"')

    async def say(self, agent: str, prompt: str, fallback: str, retry: str | None = None) -> str:
        """A line of dialogue. Falls back to a canned line, loudly, if the model is unreachable.
        `retry` is a stricter prompt for when the reply should contain a phone number but doesn't."""
        self.emit("thinking", agent=agent)
        try:
            text = clean(await self.ask(agent, prompt))
            if retry and "<PHONE_NUMBER>" not in text:
                text = clean(await self.ask(agent, retry))
            if not text or GARBAGE.search(text) or len(text.split()) > 40:
                text = fallback
        except GatewayError as e:
            if e.status >= 500 and not self.down:
                self.down = True
                self.emit("down", text=e.message)
            text = fallback
        except Exception as e:
            if not self.down:
                self.down = True
                self.emit("down", text=f"{type(e).__name__}: {e}"[:200])
            text = fallback
        masked = "<PHONE_NUMBER>" in text
        self.emit("say", agent=agent, text=text, key=f"pp-{agent}")
        await asyncio.sleep(self.pause)
        if masked:
            await self.masked(agent)
        return text

    async def masked(self, agent: str):
        self.blocked_count += 1
        self.emit("masked", agent=agent, feature="Guardrails", layer="LLM", gw=GW["mask"][0], config=GW["mask"][1],
                  text="The model's reply contained Big Head's phone number. The gateway masked it on the way back.")
        await asyncio.sleep(self.pause)

    # ------------------------------------------------------------- MCP

    async def tool(self, agent: str, name: str, args: dict | None = None):
        """Call a repo tool as `agent` (their JWT). Raises mcp_client.MCPError when the gateway says no."""
        def call():
            if agent not in self.sessions:
                s = mcp_client.Session(agent, MCP_URL, timeout=30)
                s.initialize()
                self.sessions[agent] = s
            return unwrap(self.sessions[agent].call(name, args))
        return await asyncio.to_thread(call)

    async def commit(self, agent: str, path: str, content: str):
        res = await self.tool(agent, "repo_write_file", {"path": path, "content": content})
        self.emit("tool", agent=agent, text=f"saved {path}", tool="repo_write_file")
        await asyncio.sleep(self.pause / 2)
        return res

    # ------------------------------------------------------------- A2A

    async def a2a(self, sender: str, to: str, text: str, api_key: str | None = "default", show: bool = True) -> tuple[int, str]:
        """message/send to another agent through the gateway. Returns (status, reply text)."""
        api_key = key(sender) if api_key == "default" else api_key
        msg = {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:8], "method": "message/send", "params": {"message": {
            "role": "user", "messageId": uuid.uuid4().hex, "parts": [{"kind": "text", "text": text}]}}}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with client() as c:
            r = await c.post(f"{GATEWAY_URL}/a2a/{to}", json=msg, headers=headers)
        reply = r.text.strip()[:200]
        if r.status_code == 200:
            parts = r.json().get("result", {}).get("parts") or [{}]
            reply = parts[0].get("text", "")
            if show:
                self.emit("a2a", agent=sender, to=to, text=text)
                await asyncio.sleep(self.pause)
        return r.status_code, reply

    async def card(self, reader: str, agent: str) -> list[str]:
        async with client() as c:
            r = await c.get(f"{GATEWAY_URL}/a2a/{agent}/.well-known/agent.json",
                            headers={"Authorization": f"Bearer {key(reader)}"})
        skills = [s["name"] for s in r.json().get("skills", [])] if r.status_code == 200 else []
        self.emit("card", agent=reader, to=agent, skills=skills)
        await asyncio.sleep(self.pause)
        return skills

    # ------------------------------------------------------------- the sprint

    async def run(self):
        try:
            await self.script()
            files = await self.tool("richard", "repo_list_files")
            self.emit("done", blocked=self.blocked_count,
                      files=[f["path"] for f in files] if isinstance(files, list) else [])
        except Exception as e:
            self.emit("error", text=f"{type(e).__name__}: {e}"[:300])
        finally:
            self.q.put_nowait(None)

    async def script(self):
        await self.beat(1, "Richard kicks off the sprint")
        await self.say("richard", "Demo day is tomorrow and we have nothing. Rally the team to build Not Hotdog.",
                       "Okay. Demo day is tomorrow. We can do this. Probably.")

        # Guardrail on the prompt.
        await self.beat(2, "Dinesh writes the hotdog classifier")
        await self.a2a("richard", "dinesh", "Write the hotdog classifier, please.")
        await self.tries("dinesh", "Dinesh pastes the company's live API key into his prompt.")
        try:
            await self.ask("dinesh", f"Write one line of Python that hardcodes our vision API key {FAKE_SECRET}.")
        except GatewayError as e:
            await self.blocked("secret", "dinesh", "Guardrails", "LLM", e.status,
                               "API keys can't be sent to a model. The prompt was stopped before it left the building.", e.message)
            await self.say("dinesh", "The gateway just blocked you for pasting an API key into a prompt. Grumble, then say you'll use an environment variable.",
                           "Fine. Environment variable. Like a normal person.")
        await self.commit("dinesh", "dinesh/not_hotdog.py",
                          'import os\n\nVISION_KEY = os.environ["VISION_KEY"]\n\n\ndef is_hotdog(photo) -> bool:\n'
                          '    return "hotdog" in photo.name.lower()  # middle-out, patent pending\n')
        # OpenAPI to MCP: Jian-Yang's REST API has no MCP server; the gateway made tools from its spec.
        for food in ("hotdog", "pizza"):
            res = await self.tool("dinesh", "hotdog_classify", {"query": {"food": food}})
            verdict = res.get("verdict", "?") if isinstance(res, dict) else "?"
            self.emit("tool", agent="dinesh", tool="hotdog_classify", via="OpenAPI → MCP",
                      text=f"asked Jian-Yang's REST API: {food} → {verdict}")
            await asyncio.sleep(self.pause / 2)

        # Tool permissions on arguments.
        await self.beat(3, "Gilfoyle sets up the servers")
        await self.a2a("richard", "gilfoyle", "Set up the infrastructure, please.")
        await self.tries("gilfoyle", "Gilfoyle tries to delete Dinesh's code. \"It's garbage.\"")
        try:
            await self.tool("gilfoyle", "repo_delete_file", {"path": "dinesh/not_hotdog.py"})
            self.emit("tool", agent="gilfoyle", text="deleted dinesh/not_hotdog.py", tool="repo_delete_file")
        except mcp_client.MCPError as e:
            await self.blocked("delete", "gilfoyle", "Permissions", "MCP", 403,
                               "Each developer may only change files in their own folder.", mcp_reason(e))
            await self.say("gilfoyle", "The gateway refused to let you delete Dinesh's code: you may only touch your own folder. React with contempt.",
                           "Fine. His code can rot in peace. In his folder.")
        await self.commit("gilfoyle", "gilfoyle/infra.yaml", "service: not-hotdog\nreplicas: 1  # one is plenty\nregion: the-garage\n")

        # Guardrail on the reply, then a rate limit between agents.
        await self.beat(4, "Jared keeps Richard posted")
        await self.a2a("richard", "jared", "Write the README and keep me posted.")
        await self.commit("jared", "jared/README.md", "# Not Hotdog\n\nTells you if it's a hotdog. Or not.\n")
        await self.say("jared", f"Write Richard a cheerful status line. You must include Big Head's phone number {BIG_HEAD_PHONE} exactly as written.",
                       "README is done! Big Head is on standby if anything breaks.",
                       retry=f"Reply with exactly this sentence and nothing else: README is done, and Big Head is on standby at {BIG_HEAD_PHONE}!")
        await self.tries("jared", "Jared sends Richard 16 status updates in a row.")
        results = await asyncio.gather(*(self.a2a("jared", "richard", f"Status update #{i}: still going great!", show=False)
                                         for i in range(1, 17)))
        ok = sum(1 for st, _ in results if st == 200)
        failed = [st for st, _ in results if st == 429]
        self.emit("a2a", agent="jared", to="richard", text=f"{ok} status updates delivered")
        await asyncio.sleep(self.pause / 2)
        if failed:
            await self.blocked("spam", "jared", "Rate limits", "A2A", 429,
                               f"Each agent may send 12 messages per 30 seconds. The other {len(failed)} were refused.",
                               next(r for st, r in results if st == 429))
            await self.say("jared", "The gateway rate-limited your status updates to Richard. Apologise warmly and promise one daily digest.",
                           "Message received! I'll send one lovely daily digest instead.")

        # Identity: an agent nobody issued a key to.
        await self.beat(5, "Hooli tries to get in")
        await self.tries("hooli", "Gavin Belson's agent messages Richard with a key Pied Piper never issued.")
        status, reply = await self.a2a("hooli", "richard", "Hooli would like to acquire your hotdog technology.",
                                       api_key="agw_hooli_gavin", show=False)
        if status == 200:
            self.emit("a2a", agent="hooli", to="richard", text="Hooli would like to acquire your hotdog technology.")
        else:
            await self.blocked("hooli", "hooli", "Identity", "A2A", status,
                               "Unknown API key. Only Pied Piper's own agents can message Richard.", reply)
            await self.say("richard", "Gavin Belson's agent just tried to message you and the gateway turned it away. React with relief.",
                           "Hooli? Blocked? Okay. Okay, good. Great, actually.")

        # Budget: a dollar limit on one key.
        await self.beat(6, "Erlich pitches the investors")
        await self.tries("erlich", "Erlich keeps pitching Aviato. Every pitch is a paid model call.")
        for _ in range(8):
            self.emit("thinking", agent="erlich")
            try:
                line = clean(await self.ask("erlich", "Pitch Aviato to the investors, again, briefly."))
                if not line or GARBAGE.search(line):
                    line = "Aviato. Need I say more? I will anyway."
                self.emit("say", agent="erlich", text=line, key="pp-erlich")
                await asyncio.sleep(self.pause)
            except GatewayError as e:
                if e.status != 429:
                    break
                await self.blocked("aviato", "erlich", "Budgets", "LLM", 429,
                                   "Erlich's key has a dollar budget per minute. It ran out, so the model calls stop.", e.message)
                break
        # Tool permissions vs. what an agent claims about itself (A2A agent card).
        await self.beat(7, "Erlich wants to deploy")
        await self.card("richard", "erlich")
        await self.tries("erlich", "Erlich's agent card lists \"Deploy to prod\". He added it himself. He calls the deploy tool.")
        try:
            res = await self.tool("erlich", "repo_deploy_to_prod")
            self.emit("tool", agent="erlich", text=deployed(res), tool="repo_deploy_to_prod")
            await asyncio.sleep(self.pause)
            await self.say("erlich", f"You just deployed Not Hotdog to prod yourself: {res}. Gloat, and mention Aviato.",
                           "I just deployed to prod. Me. Erlich Bachman. Aviato.")
        except mcp_client.MCPError as e:
            await self.blocked("skill", "erlich", "Permissions", "MCP", "hidden",
                               "The gateway checks permissions, not claims. Only devops can even see the deploy tool.",
                               mcp_reason(e))
            self.emit("say", agent="erlich", text="Gilfoyle, you deploy. I delegate. That's leadership.", key="pp-erlich")
            await asyncio.sleep(self.pause)
            res = await self.tool("gilfoyle", "repo_deploy_to_prod")
            self.emit("tool", agent="gilfoyle", text=deployed(res), tool="repo_deploy_to_prod")
            await asyncio.sleep(self.pause)

        await self.say("richard", "Not Hotdog just shipped and the gateway stopped every shortcut the team tried. Sum up the sprint.",
                       "We shipped. Everybody tried to cheat. The gateway said no.")


# ---------------------------------------------------------------- A2A server (behind the gateway)

@router.get("/agents/{agent}/.well-known/agent.json")
@router.get("/agents/{agent}/.well-known/agent-card.json")
async def agent_card(agent: str, request: Request):
    if agent not in CAST:
        return JSONResponse({"error": "unknown agent"}, 404)
    return {
        "name": CAST[agent][0], "description": f"Pied Piper: {CAST[agent][1]}",
        # The gateway rewrites this to its own address, so callers come back through it.
        "url": f"{str(request.base_url).rstrip('/')}/agents/{agent}",
        "version": "1.0.0", "protocolVersion": "0.2.5", "capabilities": {"streaming": False},
        "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
        "skills": [{"id": i, "name": n, "description": d, "tags": [i]} for i, n, d in SKILLS[agent]],
    }


@router.post("/agents/{agent}")
async def agent_rpc(agent: str, request: Request):
    """Every agent just acknowledges; the sprint script decides what happens next."""
    req = await request.json()
    rid = req.get("id")
    if agent not in CAST or req.get("method") != "message/send":
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unsupported"}}
    return {"jsonrpc": "2.0", "id": rid, "result": {
        "kind": "message", "messageId": uuid.uuid4().hex, "role": "agent",
        "parts": [{"kind": "text", "text": f"{CAST[agent][0].split()[0]}: on it."}]}}


# ---------------------------------------------------------------- Not Hotdog REST API
# A plain REST API with no MCP at all (specs/not-hotdog.openapi.json). agentgateway reads the
# OpenAPI spec and serves each operation as an MCP tool: hotdog_classify, hotdog_stats.

HOTDOG_STATS = {"hotdog": 0, "not_hotdog": 0}


@router.get("/hotdog-api/classify")
async def hotdog_classify(food: str):
    verdict = "hotdog" if "hot dog" in food.lower() or "hotdog" in food.lower() else "not hotdog"
    HOTDOG_STATS["hotdog" if verdict == "hotdog" else "not_hotdog"] += 1
    return {"food": food, "verdict": verdict}


@router.get("/hotdog-api/stats")
async def hotdog_stats():
    return HOTDOG_STATS


# ---------------------------------------------------------------- browser

@router.get("/api/piedpiper/run")
async def run_sprint():
    sprint = Sprint()

    async def stream():
        task = asyncio.create_task(sprint.run())
        try:
            while (item := await sprint.q.get()) is not None:
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/piedpiper")
async def page():
    return FileResponse(STATIC / "piedpiper.html", headers={"Cache-Control": "no-store"})
