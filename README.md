# Production-Ready Agent Infrastructure & Agent Gateways

Slides and demo from my talk at the AAIF meetup in Singapore, October 2026: an introduction to
[agentgateway](https://agentgateway.dev), an open-source gateway for LLM, MCP and A2A traffic.

| What                                           | Where                                                                                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Slides (PDF)                                   | [`agentgateway-aaif-talk.pdf`](agentgateway-aaif-talk.pdf)                                                                   |
| Live demo: agentgateway setup + Pied Piper app | [`agentgateway-demo/`](agentgateway-demo/), with setup steps in [`agentgateway-demo/README.md`](agentgateway-demo/README.md) |
| The gateway config (all features in one file)  | [`agentgateway-demo/config.template.yaml`](agentgateway-demo/config.template.yaml)                                           |

Quick start (needs agentgateway v1.6.0, Docker and an OpenAI-compatible model API key):

```bash
cd agentgateway-demo
cp .env.example .env    # set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
make up                 # backends + gateway config
make gateway            # second terminal
make piedpiper          # open the demo, press Start
```

Chee Hong Ngu · [github.com/potateros](https://github.com/potateros)
