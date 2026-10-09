"""Render config.yaml from config.template.yaml using values from .env.

Tracing to Langfuse is included only when LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set, so the gateway doesn't log export errors when no collector is running.

Usage: python3 scripts/render_config.py [--env .env] [--out config.yaml]
"""
import argparse
import base64
import os
import pathlib
import re
import string

ROOT = pathlib.Path(__file__).resolve().parent.parent

AGW_HOME = pathlib.Path.home() / ".config" / "agentgateway"

DEFAULTS = {
    # The native agentgateway runs on the host; backends publish on localhost.
    "REPO_MCP_URL": "http://localhost:14003/mcp",
    # Jian-Yang's Not Hotdog REST API (served by the demo app) and its OpenAPI spec.
    "HOTDOG_API_HOST": "localhost:8000",
    "HOTDOG_OPENAPI": str(ROOT / "specs" / "not-hotdog.openapi.json"),
    "KEYS_DIR": str(ROOT / "keys"),
    "DB_URL": f"sqlite://{AGW_HOME / 'data.db'}",
    "BUDGET_TAG": "v1",
    "LANGFUSE_OTLP_ENDPOINT": "http://localhost:3000/api/public/otel",
}


def load_env(path: pathlib.Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(ROOT / ".env"))
    ap.add_argument("--out", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    values = {**DEFAULTS, **load_env(pathlib.Path(args.env)), **{k: v for k, v in os.environ.items() if k in DEFAULTS}}
    template = (ROOT / "config.template.yaml").read_text()

    missing = [k for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL") if not values.get(k)]
    if missing:
        raise SystemExit(f"set {', '.join(missing)} in .env (see .env.example)")

    pk, sk = values.get("LANGFUSE_PUBLIC_KEY"), values.get("LANGFUSE_SECRET_KEY")
    if pk and sk:
        values["LANGFUSE_AUTH"] = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        template = template.replace("#TRACING_START\n", "").replace("#TRACING_END\n", "")
        print("tracing: enabled ->", values["LANGFUSE_OTLP_ENDPOINT"])
    else:
        template = re.sub(r"#TRACING_START\n.*?#TRACING_END\n", "", template, flags=re.S)
        print("tracing: disabled (set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env to enable)")

    # safe_substitute leaves $-style env references for agentgateway itself.
    rendered = string.Template(template).safe_substitute(values)
    pathlib.Path(args.out).write_text(rendered)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
