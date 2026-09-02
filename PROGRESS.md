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
- [x] **Phase 3 — Secure tool layer**: `app/tools/registry.py` — explicit `TOOL_REGISTRY` mapping
      intent strings (`PROFILE`, `DEVICE_DETAILS`, `BALANCE`, `PURCHASE_HISTORY`, `OFFERS`) to their
      tool functions, plus `execute_tool(intent, customer)` that rejects anything not in the
      allow-list (raises `UnknownIntentError`) — no arbitrary URLs/functions ever reach a call site.
      Tested in `tests/test_registry.py` (dispatch per intent, rejects `UNKNOWN`, rejects an
      arbitrary string).
- [x] **Phase 4 — Intent router**: `app/services/llm.py` (`classify_intent`, Azure OpenAI chat
      completions via the unified v1 API surface — `base_url` ending in `/openai/v1`, not the
      classic `azure_endpoint`/`api_version` client — JSON-object mode, `reasoning_effort="minimal"`
      + `max_completion_tokens=200` for gpt-5-series speed, 4s timeout, single call — no separate
      spell-check step, typo tolerance is handled in-prompt) + `app/router/intent_router.py`
      (`route_intent`) + `app/router/schemas.py` (`RouterResult`). Any LLM failure
      (timeout/API error/malformed JSON) degrades to a safe `UNKNOWN`/0.0 fallback rather than
      raising or guessing — verified live via `uvicorn` with blank Azure OpenAI credentials: returns
      a 200 clarification response, not a 500. Requires `openai>=3.7.0` — the `1.51.0` originally
      pinned predates gpt-5-series support (`reasoning_effort` param).
      **Model choice**: benchmarked `gpt-5.4-nano` vs `gpt-5-mini` live against the user's own Azure
      OpenAI resource (2026-09-03) on the plan's own example phrases — nano passed 7/7 single-shot
      classifications vs mini's 6/7, both ~2/3 on candidate-constrained clarification follow-ups
      (misses landed right at the 0.80 threshold, not a clear model-quality gap), latency
      comparable (~1.2–2.9s per call either way). Went with **`gpt-5.4-nano`** (`AZURE_OPENAI_DEPLOYMENT`)
      since it matched-or-beat mini here at ~1/5th the token cost — small sample (10 phrases total),
      revisit if real traffic shows otherwise.
- [x] **Phase 5 — Confidence + clarification**: `app/router/confidence.py` (`build_router_result`)
      enforces `INTENT_CONFIDENCE_THRESHOLD` and an intent allow-list (derived from
      `TOOL_REGISTRY.keys()`, so an out-of-list or hallucinated intent — e.g. `DELETE_ACCOUNT` — is
      always routed to clarification even at high stated confidence). `app/services/session_store.py`
      holds in-memory `PendingClarification` (possible_intents) per `session_id` so a follow-up
      answer ("the available ones") is classified against the narrowed candidate set rather than
      from scratch.
- [x] **Phase 6 — Chat endpoint** (`POST /api/chat`): `app/api/chat.py`. Flow: session lookup →
      `route_intent` (constrained to pending candidates if any) → clarification response (no tool
      call) or `execute_tool` via the Phase 3 registry → templated answer. `mobile_number` is a
      required request field for now — sourced directly from the caller, never the model/message
      text — per the seam `customer_context.py` already documents; Phase 11 auth will replace it
      with a session-derived value. Added a `type: "error"` response variant (schema superset of
      the plan's answer/clarification examples) so a downstream telecom API failure returns 200
      with a friendly message instead of a 500.
- [x] **Phase 7 — Tests + latency optimization**: `tests/test_llm.py`, `test_confidence.py`,
      `test_intent_router.py`, `test_session_store.py`, `test_response.py`, `test_chat_api.py` (53
      tests total, all passing, no live network calls — LLM and telecom calls are mocked).
      `app/services/response.py` renders answers via deterministic per-intent templates (no second
      LLM call on the fast path) built from real field shapes captured live against the telecom POC
      API (`mainWallet.balance`, `plan.planName`, etc. — see git history for full sample payloads).
      Reworked 2026-09-03 after live testing: the originals were one-line summaries, so "show me
      the offers" got the same teaser three times. They now list everything (all offers with
      price/validity/description, all purchases, full balance breakdown, device/SIM/network,
      plan price/validity/flags), multi-line, with ₹ for INR. Also fixed a real bug: the API
      returns purchases oldest-first and the old template called `transactions[0]` the "most
      recent" — it now sorts by `purchasedAt` descending.
      Existing request-logging middleware already reports `total_latency_ms` per request, so
      `/api/chat` latency is visible without extra instrumentation.
- [x] **Phase 8 — Realtime Voice — confirmed working end-to-end by a human on 2026-09-03**, full
      loop: mic → server VAD → transcription → model → tool call → real telecom API → spoken answer,
      including multi-turn conversation, interruption/truncation (barge-in), and Hindi/English
      switching. Two real bugs found and fixed from that session: (1) the model defaulted to Hindi
      instead of matching the caller's actual language (e.g. Telugu) — fixed by adding an explicit
      "always reply in whatever language the caller just used" instruction to `INSTRUCTIONS` in
      `app/services/realtime.py`; (2) perceived voice inconsistency (sounded like it switched
      speaker) turned out **not** to be a bug — `voice: "alloy"` is hardcoded and never varies
      per-request, confirmed by reading the code; likely just that voice's natural prosody varying
      across languages/interruptions. All 5 tools (`get_profile`, `get_device_details`,
      `get_balance`, `get_purchase_history`, `get_offers`) verified live via both `/api/chat` and
      `/api/voice/tool` on 2026-09-03.
      `app/services/realtime.py` (`create_realtime_session`) mints a
      short-lived ephemeral token via Azure's GA endpoint (`POST {endpoint}/realtime/client_secrets`)
      — the long-lived `AZURE_OPENAI_API_KEY` never reaches the browser, only the ephemeral token +
      public `realtime_url` do. `app/api/voice.py` exposes that as `POST /api/voice/session`, plus
      `POST /api/voice/tool` — the endpoint the browser calls when the realtime model requests a
      function call; validates the function name against `FUNCTION_NAME_TO_INTENT` (asserted equal
      to `TOOL_REGISTRY.keys()` at import time) and dispatches through the *same* Phase 3
      `execute_tool` registry chat uses, per the plan's "don't duplicate telecom tools for voice"
      rule. Voice's 5 realtime tools are zero-argument by design — mobileNumber is never a model-
      supplied parameter, same rule as chat.
      **Frontend**: `app/static/index.html`, served at `GET /` — a single dependency-free HTML/JS
      page (no framework, no web fonts, inline SVG icons), redesigned 2026-09-03 into a ChatGPT-style
      dark layout: sidebar (New chat, account number, voice status, debug-log toggle) + **one unified
      conversation thread** where typed messages and voice turns both render as bubbles, and a
      single composer bar whose mic button switches it into voice mode (level meter + stop). Text
      still goes through `/api/chat` (fast intent-router path; clarification replies render the
      `possible_intents` as clickable chips that resolve via the same session); voice goes WebRTC
      straight from the browser to Azure's `/realtime/calls` SDP endpoint using the ephemeral token;
      on `response.function_call_arguments.done` it calls `/api/voice/tool` and feeds the result
      back via a `function_call_output` conversation item. Raw realtime/RTC events go to a
      collapsible debug drawer instead of the main thread. Deliberately **omits**
      the docs' `?webrtcfilter=on` query param — that filter's allow-listed event set does not
      include `response.function_call_arguments.done`, which would silently break tool calling.
      Also added a live mic-level meter (Web Audio `AnalyserNode`) to the Voice panel, independent
      of Azure entirely — useful for isolating "browser isn't capturing audio" from "Azure isn't
      responding" if voice ever seems dead again. Tested with mocks: `tests/test_realtime.py`,
      `tests/test_voice_api.py`.
- [ ] **Phase 9 — LangGraph fallback**: not started.
- [ ] **Phase 10 — Azure VM deployment**: not started. See "Deployment notes" below — SSH from the
      original dev machine is blocked by a corporate firewall, so deployment is git-pull-on-the-VM,
      not push-from-here.

## Open decisions

1. ~~LLM backend for the router/chat~~ — **Resolved 2026-09-02: Azure OpenAI**, matching the
   existing `.env.example` (`AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY`). Phase 4
   (`app/services/llm.py` + intent router) should build against the Azure OpenAI SDK.
2. GitHub repo: `https://github.com/v-adityaram/telecom-assistant` (already set as `origin`, `main`
   branch). Auth is via a GitHub PAT stored in this machine's Git Credential Manager — **that
   credential does not travel with the repo**; a new machine needs its own token (see README).

## Not yet verified

- Live-tested against the real Azure OpenAI resource on 2026-09-03 (see Phase 4 above) — single-shot
  classification and the full `/api/chat` flow (including a real telecom API answer) both work.
  **Still open**: candidate-constrained clarification follow-ups ("the available ones" after being
  asked profile-vs-offers) come back right around the 0.80 confidence threshold and sometimes
  re-trigger a second clarification instead of resolving — seen with both nano and mini. Worth
  either lowering `INTENT_CONFIDENCE_THRESHOLD` specifically for the follow-up path, or tightening
  `CANDIDATE_NOTE_TEMPLATE` in `app/services/llm.py` to push confidence higher when only two
  well-separated candidates remain, once there's more real traffic to tune against.
- The Azure OpenAI API key used for this testing was pasted into a chat session — rotate it in the
  Azure portal once done testing, then update the local `.env` (never committed) with the new key.

## Deployment notes (for Phase 10, when we get there)

- Target VM: Azure 1 GB Ubuntu, public IP `104.211.224.38`, user `azureuser`.
- **Outbound SSH is machine/network-dependent, not VM-side.** The machine used to build Phase 1–2
  sat behind a corporate network that blocked outbound port 22 entirely (confirmed against both the
  VM and `github.com:22`). Re-tested from a different machine on 2026-09-03: port 22 is open and a
  password-auth SSH login succeeds fine. So the "deploy via Azure Portal console" workaround below
  is a fallback for a blocked network, not a hard requirement — check `nc`/`Test-NetConnection` to
  `104.211.224.38:22` first; if it's open, a normal `git clone`/`git pull` over SSH from that machine
  works.
- **VM state as of 2026-09-03**: `~/telecom-assistant` exists but is *not* a git checkout — it only
  has a `venv/` directory, no code. Nothing has actually been deployed yet; Phase 10 (clone the repo,
  install deps, wire up nginx + a systemd service for uvicorn) is still fully ahead of us.
  `~/voice-agent` is a separate, apparently unrelated folder (own `.venv`, a small `main.py`) — not
  part of this project's plan, left untouched.
- Fallback workaround (if SSH is blocked from wherever you're building): build and test everything
  locally, push to GitHub, then `git pull` directly on the VM via Azure Portal browser SSH/Serial
  Console instead of pushing from the dev machine.
- Do not run a local LLM, Ollama, Elasticsearch, or Kubernetes on the VM — 1 GB RAM. Nginx + one
  FastAPI (uvicorn) process only; add swap as a safety margin.

## Known environment quirks worth knowing about

- This dev machine required `truststore` (see `app/services/telecom_client.py`) to make outbound
  HTTPS calls succeed at all — corporate network TLS-inspects traffic with its own root CA, which
  Windows trusts but Python's default `certifi` bundle does not. If a *different* machine (e.g. the
  Azure VM itself) hits TLS errors calling the telecom API, check whether it's the same cause before
  assuming `truststore` is still needed — it may not be, on a network without TLS inspection.
