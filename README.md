# Project Structure
```
voiceops-mcp/
├── LICENSE                     # MIT or Apache-2.0 (needed for Open Source challenge)
├── README.md                   # D: what it is, architecture diagram, 5-min quickstart
├── FRICTION_LOG.md             # D: everyone appends entries as they hit problems
├── PRODUCT_FEEDBACK.md         # B/D: per tool, API, SDK, and AWS service used
├── .env.example                # no real secrets, ever
├── docker-compose.yml          # one command: server + mock containers + simulator
├── Makefile                    # make dev | make test | make demo
│
├── contracts/                  # A owns, published Day 1
│   ├── tools.schema.json       # tool names, inputs, outputs (everyone builds against this)
│   └── errors.md               # error codes and spoken-friendly messages
│
├── server/                     # A: the MCP server
│   ├── main.py                 # Streamable HTTP entry point
│   ├── auth.py                 # bearer token / OAuth, rate limiting
│   ├── audit.py                # append-only log of every tool call
│   ├── docker_client.py        # Docker socket wrapper (read-only by default)
│   └── tools/
│       ├── containers.py       # list_containers, get_container_status
│       ├── logs.py             # tail_logs
│       ├── metrics.py          # get_system_metrics
│       └── actions.py          # propose_action, confirm_action
│
├── safety/                     # C: imported by server/tools/actions.py
│   ├── confirmation.py         # token issue/verify, expiry (e.g. 60s), single use
│   ├── policy.py               # allowlist of restartable containers, deny "all"
│   └── voice_messages.py       # spoken wording for confirmations and errors
│
├── agent/                      # B: Bedrock / Strands layer
│   ├── agent.py                # diagnose "why is X down?", summarize logs
│   ├── prompts/                # system prompts, kept as files for easy iteration
│   └── summarize.py            # shorten output to speakable length
│
├── infra/                      # B: deployment
│   ├── deploy.md               # exact steps, reproducible
│   ├── Dockerfile
│   └── (cdk/ or terraform/ or scripts/)
│
├── sim/                        # D: Alexa+ simulator web app (fallback + demo visual)
│   ├── src/                    # chat/voice UI, live container status panel
│   └── README.md               # clearly documents it for judging
│
├── mock-env/                   # C: disposable containers for demos and tests
│   ├── compose.mock.yml        # a few fake services you can safely break
│   └── scenarios/              # "crash loop", "high memory", "healthy"
│
├── tests/                      # C
│   ├── unit/                   # tools, safety policy, token expiry
│   ├── integration/            # server + mock-env
│   └── adversarial/            # "restart everything", replayed tokens, injection in logs
│
├── docs/                       # D
│   ├── architecture.md
│   ├── demo-script.md
│   └── devpost-draft.md
│
└── .github/workflows/ci.yml    # lint + tests on every PR
```