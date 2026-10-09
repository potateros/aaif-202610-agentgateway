.PHONY: keys config check gateway install fresh-budget up down logs ui piedpiper reset-repo inspector test

# The native agentgateway reads this file (and hot-reloads it).
AGW_CONFIG := $(HOME)/.config/agentgateway/config.yaml

keys:            ## generate a signing key, the JWKS, and one JWT per character (30-day expiry)
	docker compose --profile tools run --rm tools keys/gen_keys.py

config:          ## render config.yaml from config.template.yaml + .env
	@test -f .env || cp .env.example .env
	python3 scripts/render_config.py

check: config    ## validate config with the installed agentgateway binary
	@set -a; . ./.env; set +a; agentgateway -f config.yaml --validate-only

gateway:         ## run the native agentgateway in this terminal with .env loaded (Ctrl+C stops it)
	@set -a; . ./.env; set +a; exec agentgateway

install: check   ## copy the rendered config over the native gateway's config
	@mkdir -p $(dir $(AGW_CONFIG))
	@test ! -f $(AGW_CONFIG) || test -f $(AGW_CONFIG).pre-demo || cp $(AGW_CONFIG) $(AGW_CONFIG).pre-demo
	cp config.yaml $(AGW_CONFIG)
	@echo "installed -> $(AGW_CONFIG)"

fresh-budget:    ## give Erlich a fresh budget (usage is stored per budget name)
	@test -f .env || cp .env.example .env
	@sed -i '' '/^BUDGET_TAG=/d' .env
	@echo "BUDGET_TAG=$$(date +%Y%m%d%H%M%S)" >> .env
	$(MAKE) install

up: config       ## build and start the backends, then install the gateway config
	@test -f keys/jwks.json || $(MAKE) keys
	docker compose up -d --build
	$(MAKE) install
	@echo "Pied Piper: http://localhost:8000/piedpiper   gateway UI: http://localhost:4000/ui"

down:            ## stop the backends (the gateway keeps running)
	docker compose down

logs:            ## backend logs (gateway logs are in the terminal running `make gateway`)
	docker compose logs -f

ui:              ## open the agentgateway UI
	open http://localhost:4000/ui

piedpiper:       ## open the Pied Piper page
	open http://localhost:8000/piedpiper

reset-repo:      ## empty the fake repo (hotdog-app/) between runs
	find hotdog-app -mindepth 1 ! -name .gitkeep -delete

test:            ## run the app's unit tests (no network) inside the app container
	docker compose run --rm --no-deps app python -m pytest -q app

# MCP Inspector (the official MCP debugger) on the gateway's /mcp, logged in as one character.
# Shows Jian-Yang's REST API as MCP tools (hotdog_classify, hotdog_stats): OpenAPI to MCP.
# The token is read from keys/<user>.jwt and never printed. Example: make inspector WHO=gilfoyle
# Note: the Inspector's Network tab shows the token when you expand a request.
WHO ?= dinesh
inspector:       ## open MCP Inspector on localhost:4000/mcp as $(WHO) (default dinesh)
	@test -f keys/$(WHO).jwt || { echo "no keys/$(WHO).jwt (run make keys)"; exit 1; }
	@echo "MCP Inspector -> http://localhost:4000/mcp as $(WHO). Ctrl+C to stop."
	@npx -y @modelcontextprotocol/inspector --web --transport http --server-url http://localhost:4000/mcp \
		--header "Authorization: Bearer $$(cat keys/$(WHO).jwt)"
