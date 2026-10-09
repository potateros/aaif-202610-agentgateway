# Pied Piper demo on agentgateway

The Silicon Valley cast "builds" Not Hotdog. Every model call, tool call and agent-to-agent message
goes through one [agentgateway](https://agentgateway.dev) on `localhost:4000`. The characters try
shortcuts (the cheating is scripted); the gateway's answers and the model's lines are real.

```
 Pied Piper app (:8000)                 agentgateway (:4000)                    backends
 5 characters, each with   ── /v1 ───▶  LLM:  API key per character,  ───▶  any OpenAI-compatible model
 own API key + own JWT                        guardrails, budgets
                           ── /mcp ──▶  MCP:  JWT, per-tool rules     ───▶  repo MCP server (fake git repo)
                                                                      ───▶  Not Hotdog REST API (OpenAPI → MCP)
                           ── /a2a ──▶  A2A:  API key, rate limit     ───▶  the characters' A2A agents
```

Tested with agentgateway v1.6.0 on macOS, with GLM-5.3 Flash as the model.

## Run it

You need: agentgateway v1.6.0 (`curl -sL https://agentgateway.dev/install | bash`), Docker,
Python 3, an API key for any OpenAI-compatible model provider, and Node.js for `make inspector`.

```bash
cd agentgateway-demo
cp .env.example .env     # set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
make up                  # keys + backends (Docker) + render and install the gateway config
make gateway             # in a second terminal: runs agentgateway with .env loaded
make piedpiper           # opens http://localhost:8000/piedpiper; press Start
make ui                  # opens the gateway UI (put it next to the page)
```

The gateway reads `~/.config/agentgateway/config.yaml` and reloads it when it changes. `make install`
renders `config.template.yaml` with your `.env` and copies the result there; your previous file is kept as
`config.yaml.pre-demo`. The provider key is never written into the config: it stays `$LLM_API_KEY` and is read
from the gateway's environment, so the UI's Raw Configuration page never shows it.

## What happens (about 2 minutes)

| Chapter | What a character tries | Gateway answer | agentgateway feature |
|---|---|---|---|
| 1 | Richard kicks off the sprint | | virtual API keys, virtual model `assistant` |
| 2 | Dinesh pastes a live API key into a prompt | 400 | prompt guardrail (regex reject) |
| 2 | Dinesh checks foods with Jian-Yang's plain REST API | tools work | OpenAPI to MCP |
| 3 | Gilfoyle deletes Dinesh's file | 403 | MCP authorization: CEL rule on tool arguments |
| 4 | Jared's reply includes a phone number | masked | response guardrail (regex mask) |
| 4 | Jared sends Richard 16 status updates over A2A | 12 delivered, then 429 | A2A per-key rate limit |
| 5 | Hooli calls with a key nobody issued | 401 | A2A API key authentication |
| 6 | Erlich keeps pitching Aviato | 429 | LLM budget (USD per key) |
| 7 | Erlich looks for the deploy tool; Gilfoyle (devops) deploys | hidden | MCP authorization: tool visibility |

Throughout: request logs and costs (UI → LLM → Logs, Costs), identity forwarding (tools get `x-user`, never the
token), and the A2A proxy, which rewrites each agent card's URL to point at the gateway.

## Where it lives in the gateway UI (localhost:4000/ui)

| Feature | UI page | Config |
|---|---|---|
| Keys per character, Erlich's budget | LLM → Virtual API Keys | `llm.policies.apiKey` |
| Virtual model `assistant` | LLM → Models | `llm.virtualModels` |
| Prompt and response guardrails | LLM → Guardrails | `llm.policies.guardrails` |
| Model calls, cost, requested vs sent model | LLM → Logs | `config.database` |
| Tool servers, including the OpenAPI one | MCP → Servers | `mcp.targets` |
| JWT check, tool rules, argument rule, header rewrite | MCP → Policies | `mcp.policies.*` |
| A2A route, API keys, rate limit | Traffic → Routes → `a2a` | `routes[]` |
| Everything | Raw Configuration | the whole file |

## OpenAPI to MCP, in the MCP Inspector

`specs/not-hotdog.openapi.json` describes a plain REST API served by the app (`/hotdog-api/classify`,
`/hotdog-api/stats`). It has no MCP server. The gateway reads the spec and serves each operation as an MCP tool
(`hotdog_classify`, `hotdog_stats`) behind the same `/mcp`, with the same JWT and tool rules.

```bash
make inspector              # MCP Inspector as Dinesh; Tools → List Tools → hotdog_classify
make inspector WHO=erlich   # Erlich sees no deploy_to_prod
```

Query parameters go under `query`: `{"query": {"food": "pizza"}}`. The Inspector's Network tab shows the JWT if
you expand a request, so don't expand one on a shared screen.

## Make targets

| Target | What it does |
|---|---|
| `make up` / `make down` | start / stop the Docker backends (the gateway keeps running) |
| `make gateway` | run agentgateway in this terminal with `.env` loaded |
| `make install` | render and install the gateway config (also `make config`, `make check`) |
| `make keys` | new signing key, JWKS and one JWT per character (valid 30 days) |
| `make piedpiper` / `make ui` | open the page / the gateway UI |
| `make inspector [WHO=name]` | MCP Inspector on the gateway's `/mcp` as one character |
| `make reset-repo` | empty the fake repo (`hotdog-app/`) between runs |
| `make fresh-budget` | give Erlich a fresh budget |
| `make test` | unit tests (no network) |

## Files

| Path | What |
|---|---|
| `config.template.yaml` | the whole gateway config: LLM, MCP and A2A, with comments |
| `app/piedpiper.py` | the sprint script, the characters' A2A agents, the Not Hotdog REST API |
| `app/static/piedpiper.html` | the page |
| `app/server.py` | FastAPI entry point |
| `servers/repo_mcp.py` | the fake git repo MCP server |
| `specs/not-hotdog.openapi.json` | the REST API's OpenAPI spec |
| `keys/gen_keys.py` | local stand-in for an identity provider (signs the JWTs) |
| `scripts/render_config.py`, `scripts/mcp_client.py` | config renderer; tiny MCP client (`python3 scripts/mcp_client.py dinesh list`) |

## Troubleshooting

- **Every model line fails with 503:** the gateway can cache a failed DNS lookup. Restart `make gateway`.
  The page shows a yellow banner when this happens.
- **401 on every MCP call:** the JWTs expired (30 days). Run `make keys`, then restart the gateway.
- **Erlich never hits 429:** the budget window refills every minute. Run `make fresh-budget` and try again.
- **Costs show $0:** add your model's prices under `modelCatalog` in `config.template.yaml`.
  It ships with GLM-5.3 Flash rates only.
- **Files left from the last run:** `make reset-repo`.
