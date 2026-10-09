"""Minimal MCP (streamable HTTP) client with no dependencies beyond stdlib.

Deliberately tiny so the audience can read exactly what goes over the wire.

  python3 scripts/mcp_client.py dinesh list
  python3 scripts/mcp_client.py erlich list          # no deploy_to_prod: hidden by policy
  python3 scripts/mcp_client.py dinesh call hotdog_classify '{"query": {"food": "pizza"}}'
  python3 scripts/mcp_client.py gilfoyle call repo_delete_file '{"path": "dinesh/not_hotdog.py"}'   # 403
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
MCP_URL = os.environ.get("MCP_URL", "http://localhost:4000/mcp")


class MCPError(Exception):
    pass


class Session:
    def __init__(self, user: str | None, url: str = MCP_URL, headers: dict | None = None, timeout: float = 15):
        self.url = url
        self.extra_headers = headers or {}
        self.timeout = timeout
        self.token = (ROOT / "keys" / f"{user}.jwt").read_text().strip() if user else None
        self.session_id = None
        self._id = 0

    def _post(self, payload: dict):
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": "2025-06-18",
        }
        headers.update(self.extra_headers)
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self.session_id = resp.headers.get("mcp-session-id", self.session_id)
                body = resp.read().decode()
                ctype = resp.headers.get("content-type", "")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}: {e.read().decode()[:200]}") from None
        if not body.strip():
            return None
        if "text/event-stream" in ctype:
            data = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
            body = data[-1] if data else "{}"
        msg = json.loads(body)
        if "error" in msg:
            raise MCPError(json.dumps(msg["error"]))
        return msg.get("result")

    def request(self, method: str, params: dict | None = None):
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})

    def notify(self, method: str):
        self._post({"jsonrpc": "2.0", "method": method})

    def initialize(self):
        result = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "aaif-demo-client", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[str]:
        return [t["name"] for t in self.request("tools/list")["tools"]]

    def call(self, name: str, args: dict | None = None):
        result = self.request("tools/call", {"name": name, "arguments": args or {}})
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        texts = [c.get("text") for c in result.get("content", [])]
        try:
            return [json.loads(t) for t in texts]
        except (TypeError, ValueError):
            return texts


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    user, action = sys.argv[1], sys.argv[2]
    s = Session(None if user == "anonymous" else user)
    try:
        s.initialize()
        if action == "list":
            tools = s.list_tools()
            print(f"{user} can see {len(tools)} tools:")
            for t in tools:
                print("  -", t)
        elif action == "call":
            args = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
            print(json.dumps(s.call(sys.argv[3], args), indent=2))
    except MCPError as e:
        print(f"DENIED/ERROR for {user}: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
