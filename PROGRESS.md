# Progress

Tracks where this build stands against `docs/telecom_ai_assistant_implementation_plan.md`.
Read that file first for the full architecture and rules — this file is just status + open decisions,
so a session on any machine can pick up where the last one left off.

## Phase status

- [x] **Phase 1 — FastAPI foundation**: `app/main.py`, `app/config.py`, `app/logging_config.py`,
      `GET /health`. Structured request logging + global exception handler + CORS in place.
      Tested via pytest and a live server hit.
- [x] **Phase 2 — Telecom API clients**: `app/tools/{profile,device,balance,purchase_history,offers}.py`,
      `app/services/telecom_client.py` (shared async httpx client, explicit timeouts, structured
      `ToolResult(success, data, error, status_code)`), `app/services/customer_context.py` (minimal
      `CustomerContext` — real auth lands in Phase 11). Verified live against the real Azure Function
      API using the sample number from the Postman collection (`+919999900003`) — all 5 endpoints
      return 200.
- [ ] **Phase 3 — Secure tool layer** (allow-list intent → function): not started. Next up.
- [ ] **Phase 4 — Intent router**: not started. **Blocked on a decision** — see "Open decisions" below.
- [ ] **Phase 5 — Confidence + clarification**: not started.
- [ ] **Phase 6 — Chat endpoint** (`POST /api/chat`): not started.
- [ ] **Phase 7 — Tests + latency optimization**: ongoing per-phase, dedicated pass not started.
- [ ] **Phase 8 — Realtime Voice**: not started.
- [ ] **Phase 9 — LangGraph fallback**: not started.
- [ ] **Phase 10 — Azure VM deployment**: not started. See "Deployment notes" below — SSH from the
      original dev machine is blocked by a corporate firewall, so deployment is git-pull-on-the-VM,
      not push-from-here.

## Open decisions (need input before continuing)

1. **LLM backend for the router/chat (blocks Phase 4).** The plan's `.env.example` assumes Azure
   OpenAI (`AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY`), but this was never confirmed — could
   also be Anthropic Claude. Whoever picks this up next should confirm with the user and fill in
   `.env` accordingly (never commit real keys).
2. GitHub repo: `https://github.com/v-adityaram/telecom-assistant` (already set as `origin`, `main`
   branch). Auth is via a GitHub PAT stored in this machine's Git Credential Manager — **that
   credential does not travel with the repo**; a new machine needs its own token (see README).

## Deployment notes (for Phase 10, when we get there)

- Target VM: Azure 1 GB Ubuntu, public IP `104.211.224.38`, user `azureuser`.
- The machine used to build this (Phase 1–2) sits behind a corporate network that blocks *outbound*
  SSH (port 22) entirely — confirmed by testing against both the VM and a known-good host
  (`github.com:22`), both failed, while port 80 to the VM succeeded. NSG rules on the VM (ports
  22/80/8000/443, priorities 300/320/330/340) were not the blocker.
- Chosen workaround: build and test everything locally, push to GitHub, then `git pull` directly
  on the VM (via Azure Portal browser SSH/Serial Console, or from a network that isn't blocked)
  rather than pushing from the dev machine.
- Do not run a local LLM, Ollama, Elasticsearch, or Kubernetes on the VM — 1 GB RAM. Nginx + one
  FastAPI (uvicorn) process only; add swap as a safety margin.

## Known environment quirks worth knowing about

- This dev machine required `truststore` (see `app/services/telecom_client.py`) to make outbound
  HTTPS calls succeed at all — corporate network TLS-inspects traffic with its own root CA, which
  Windows trusts but Python's default `certifi` bundle does not. If a *different* machine (e.g. the
  Azure VM itself) hits TLS errors calling the telecom API, check whether it's the same cause before
  assuming `truststore` is still needed — it may not be, on a network without TLS inspection.
