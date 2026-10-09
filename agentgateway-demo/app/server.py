"""Pied Piper demo app: serves the page, the A2A agents and the Not Hotdog REST API.

Every model call, tool call and agent-to-agent message goes through agentgateway.
The sprint itself lives in piedpiper.py.
"""
import json
import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000").rstrip("/")
MCP_URL = GATEWAY_URL + "/mcp"
MODEL = "assistant"  # the gateway's virtual model; the app never names a real model
STATIC = pathlib.Path(__file__).parent / "static"


class GatewayError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @property
    def blocked(self) -> bool:
        return self.status in (400, 403, 429)


def _err_message(status: int, body: str) -> str:
    try:
        return json.loads(body)["error"]["message"]
    except Exception:
        return f"HTTP {status}: {body[:200]}"


app = FastAPI(title="Pied Piper")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return RedirectResponse("/piedpiper")


from . import piedpiper  # noqa: E402  (imports names defined above)

app.include_router(piedpiper.router)
