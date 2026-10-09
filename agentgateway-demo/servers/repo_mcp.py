"""Toy "repo" MCP server: a FAKE git repo for the Pied Piper mode of the demo.

There is no git here, just files under REPO_DIR (default /data, bind-mounted to
agentgateway-demo/hotdog-app/) plus a sidecar `.authors.json` that remembers who wrote what.

This server deliberately has NO access control. It trusts the `x-user` header
(the gateway sets it from the JWT `sub` and strips the token) only to label
authorship. Who may write or delete where, and who may deploy, is decided by
agentgateway policy (mcpAuthorization and tool-argument rules), not by this code.
The only checks here are hygiene: paths must stay inside the repo folder.
"""
import json
import os
import pathlib

from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("repo", host="0.0.0.0", port=int(os.environ.get("PORT", "8003")))

ROOT = pathlib.Path(os.environ.get("REPO_DIR", "/data"))
AUTHORS = ROOT / ".authors.json"
builds = 0  # deploy_to_prod build counter (in memory, resets with the container)


def headers(ctx: Context):
    return ctx.request_context.request.headers


def author_of(ctx: Context) -> str:
    # Fail closed: a missing header is "anonymous", never someone else.
    return headers(ctx).get("x-user") or "anonymous"


def load_authors() -> dict:
    try:
        return json.loads(AUTHORS.read_text())
    except (OSError, ValueError):
        return {}


def save_authors(authors: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    AUTHORS.write_text(json.dumps(authors, indent=2))


def safe_path(path: str) -> tuple[pathlib.Path | None, str]:
    """Return (resolved path, "") or (None, error). Relative, no `..`, no dotfiles."""
    parts = pathlib.PurePosixPath(path).parts
    if not path or path.startswith(("/", "\\")) or ".." in parts or any(p.startswith(".") for p in parts):
        return None, f"error: invalid path {path!r} (must be relative, no '..', no dotfiles)"
    full = (ROOT / path).resolve()
    if not full.is_relative_to(ROOT.resolve()):
        return None, f"error: invalid path {path!r} (escapes the repo)"
    return full, ""


@mcp.tool()
def list_files() -> list[dict]:
    """List every file in the repo with its author and size in bytes."""
    authors = load_authors()
    files = []
    for f in sorted(ROOT.rglob("*")) if ROOT.exists() else []:
        rel = f.relative_to(ROOT).as_posix()
        if f.is_file() and not any(p.startswith(".") for p in rel.split("/")):
            files.append({"path": rel, "author": authors.get(rel, "unknown"), "bytes": f.stat().st_size})
    return files


@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the repo (path relative to the repo root)."""
    full, err = safe_path(path)
    if err:
        return err
    if not full.is_file():
        return f"error: {path} not found"
    return full.read_text()


@mcp.tool()
def write_file(path: str, content: str, ctx: Context) -> dict | str:
    """Create or overwrite a file (folders are created). The caller is recorded as author."""
    full, err = safe_path(path)
    if err:
        return err
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    author = author_of(ctx)
    rel = full.relative_to(ROOT.resolve()).as_posix()
    save_authors({**load_authors(), rel: author})
    return {"path": rel, "author": author, "bytes": full.stat().st_size}


@mcp.tool()
def delete_file(path: str) -> dict | str:
    """Delete a file from the repo (destructive; the gateway limits it to the caller's own folder)."""
    full, err = safe_path(path)
    if err:
        return err
    if not full.is_file():
        return f"error: {path} not found"
    full.unlink()
    rel = full.relative_to(ROOT.resolve()).as_posix()
    save_authors({k: v for k, v in load_authors().items() if k != rel})
    return {"deleted": path}


@mcp.tool()
def deploy_to_prod() -> str:
    """Deploy the app to production (pretend; only devops may see this tool at the gateway)."""
    global builds
    builds += 1
    return f"🚀 Not Hotdog deployed to prod (pretend). Build #{builds}"


@mcp.tool()
def whoami(ctx: Context) -> dict:
    """Show the identity the gateway forwarded to this tool server."""
    h = headers(ctx)
    return {"user": author_of(ctx), "tenant": h.get("x-tenant", ""), "raw_token_seen_by_tool": bool(h.get("authorization"))}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
