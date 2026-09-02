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
- [x] **Phase 9 — LangGraph fallback**, built 2026-09-03 in response to real gaps a user hit live:
      questions like "what are my add-ons", "am I eligible for 5G", or "what roaming charges/offers
      do I have" are structurally ambiguous — the field genuinely exists in two different API
      responses (add-ons: BALANCE.addOnBalances vs OFFERS' add-on category; 5G: PROFILE's
      serviceFlags vs DEVICE_DETAILS' capability) — and no amount of prompt-tuning the single-intent
      classifier fixes that, because it's not a classification error, it's a single-tool-call
      architecture being asked a question that needs two. Advisory questions ("should I get roaming
      for my trip to Vizag") are a different problem again: not a data-fetch at all, but reasoning
      grounded in account data.
      `app/services/complex_flow.py` — a `langgraph` `StateGraph` (added as a dependency; installs
      clean against the existing pins, `pip check` reports nothing broken): `plan` (LLM picks which
      of the 5 tools are relevant, can be 0-5) -> `fetch` (calls them via `asyncio.gather`, the
      *same* Phase 3 `execute_tool` registry chat and voice already use — no new tool code) ->
      `answer` (LLM writes the actual answer grounded in the real fetched JSON, same trust model
      already proven in voice: the model never sees anything but real data, but *is* allowed to
      phrase/reason over it, unlike chat's static templates). Every node degrades to an honest
      fallback rather than raising or guessing: a planning failure yields an empty plan (not "fetch
      everything"), a hallucinated tool name is filtered before it ever reaches `execute_tool`, a
      partial fetch failure marks just that lookup as an error and still answers from the rest.
      `app/services/llm.py`'s classifier gained a 7th label, `COMPLEX` — decided in the *same*
      single LLM call already being made, so clean single-intent queries pay zero extra latency.
      `app/router/confidence.py`'s `COMPLEX_INTENT` bypasses the confidence threshold entirely (it's
      a routing decision, not a tool call to gate) and is filtered out of `possible_intents` so it
      never appears as a clarification chip. The prompt is explicit that the existing cheap
      PROFILE-vs-OFFERS "check my plan" clarification should *not* be promoted to COMPLEX — that
      one's a quick binary pick and works well as-is; COMPLEX is only for cases a clarification
      genuinely can't resolve.
      **Live-verified 2026-09-03** against the exact failing transcript: "what are my add-ons" (now
      correctly fetches both BALANCE+OFFERS, 4/4 consistent after adding a planner calibration
      example — first try only fetched OFFERS), "am I eligible for 5G" (PROFILE+DEVICE_DETAILS),
      "should I get roaming to Vizag" (correctly reasons Vizag is domestic, so international roaming
      isn't needed — genuine advice, not just data), "check my balance and offers" (both, combined).
      "esim flag?" turned out to be a single-domain gap, not a COMPLEX one — same fix pattern as the
      earlier SMS/plan wobbles, anchored in the classifier prompt instead (verified 5/5). Extended
      `scripts/live_smoke.py` with these cases; full 43-check matrix passed (one unrelated,
      pre-existing single-phrase wobble reappeared on a second run — same temperature-1 noise
      already documented above, confirmed 8/8 on a dedicated re-run, not a regression from this
      work).
      **Cost of this**: COMPLEX turns take ~8-9.5s (two sequential LLM calls — plan then answer —
      plus concurrent tool fetches) vs ~2.9s for the fast path. Worth it only because it's gated to
      genuinely multi-domain/advisory cases; every clean single-intent query still takes the
      original one-call path.
- [x] **Scope-aware chat answers** (2026-09-03, follow-on from Phase 9): a user asked "if I ask
      'sms', can it give just sms" instead of the full balance dump — the same problem COMPLEX
      solved for multi-domain questions, but this time within a *single* already-correct intent.
      `app/services/llm.py`'s classifier gained an 8th field, `scope` (`"full"` or `"specific"`),
      decided in the same call, zero extra cost for the common case. `app/services/answer_synthesis.py`
      (new, standalone — deliberately not sharing code with `complex_flow.py`'s answer node, whose
      test suite would otherwise need reworking for no real benefit) answers a narrow question
      grounded in the single tool's already-fetched real data, same trust model as everywhere else:
      never invents facts, only extracts/phrases from what was actually fetched. `chat.py` branches
      on `RouterResult.scope` — `"full"` (default) keeps the exact original fast deterministic
      template, `"specific"` calls the synthesis function instead.
      **Two real gaps found and fixed while verifying, not assumed**: (1) "is my phone 5g" was
      inconsistently DEVICE_DETAILS / UNKNOWN / a COMPLEX-flavored clarification (3/6 wrong) — it's
      genuinely ambiguous with "am I eligible for 5G" (COMPLEX); added an explicit prompt anchor
      distinguishing "phone/device" (DEVICE_DETAILS) from "eligible/plan" (COMPLEX), verified 8/8
      after. (2) "what did I buy recently" started collapsing to a single transaction under the new
      scope logic, which would wrongly imply that's the customer's only purchase (there are 3) —
      added a rule that "recently" (plural framing) stays `full` while only "last"/"most recent"
      (explicitly singular) goes `specific`, verified 4/4 and 3/3 respectively.
      `scripts/live_smoke.py`'s original per-intent assertions were pinned to the exact full-template
      wording; several of those phrasings ("am I prepaid or postpaid", "what's my SIM status", "how
      much data do I have left", "how many SMS do I have remaining") turned out to be genuinely
      narrow questions the router now — correctly — answers with `scope=specific`, so the assertions
      were rewritten to check for the underlying fact rather than the literal template string.
      Full 43-check matrix passed twice in a row after all fixes landed.
- [x] **Two more router gaps found live** (2026-09-03, same session): bare **"profile"** was being
      treated as ambiguous with OFFERS (1/5 success) — the model was over-generalizing the "plan"
      ambiguity rule to "profile" too, even though "profile" never means "offers/plans to buy" the
      way "plan" genuinely does. **Location/circle questions** ("where am I based", "location?",
      "which circle am I on") had no calibration at all and fell to the generic clarification
      (2/8 success) despite the data existing (`PROFILE.telecomCircle`). Both fixed with explicit
      prompt anchors in `app/services/llm.py`; verified 8/8 (location) and 6/6 (bare "profile") after.
      Also bumped `llm.py`'s `TIMEOUT_SECONDS` 4.0 -> 6.0 — a live run showed 3 genuine
      `llm_timeout` log entries (not classification errors) during heavy back-to-back testing, and
      real successful calls had already been observed taking up to ~4.5s, so 4.0s was cutting it too
      close for legitimate calls, not just abusive load. `scripts/live_smoke.py` extended to 47
      checks (added the two new cases as permanent regression coverage); passed 47/47 after the fix.
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

- **`scripts/live_smoke.py`** — a 37-check end-to-end matrix against a *running* server with
  real Azure OpenAI + real telecom API calls (all 5 intents × 3 phrasings incl. typos, ambiguity +
  three follow-up resolutions, small talk, number-override and URL-injection attempts, bad-number
  error path, all 5 voice tool endpoints, token minting). Not part of `pytest` — needs `.env` and
  a server on :8000. Run it after touching the router prompt, thresholds, or templates. Passed
  37/37 on two consecutive runs on 2026-09-03 (avg chat latency ~2.9s, of which the telecom API
  is ~0.6s and the rest is the gpt-5.4-nano call). **Renamed** from `live_smoke_test.py` — that name
  matched pytest's default `*_test.py` discovery pattern, so a plain `pytest -q` silently picked it
  up and ran its live network calls as if it were a unit test (crashed the whole run with an
  INTERNALERROR from the script's own `SystemExit`). Also added `pytest.ini` (`testpaths = tests`)
  so nothing outside `tests/` gets collected again by accident.
- ~~"sms"/"sms bal" and other short SMS phrasings sometimes needed clarification instead of
  resolving to BALANCE~~ — **fixed 2026-09-03**. There's no dedicated SMS intent (SMS remaining is
  a field inside BALANCE), so short bare phrases didn't give the model enough signal and it was
  inconsistent run to run (temperature-1 flakiness, same root cause as below). Added an explicit
  calibration block to `SYSTEM_PROMPT` in `app/services/llm.py` stating SMS/text queries always map
  to BALANCE. Verified 18/18 across 3 rounds on the exact phrases that were failing.
- ~~"what's my plan" sometimes resolved straight to PROFILE instead of asking~~ — **fixed
  2026-09-03**, found while re-verifying the SMS fix (1/6 repeats skipped clarification). Bare
  "plan" phrasings ("what's my plan", "check my plan", "my plan") now have an explicit always-ask
  rule in the prompt, with "current"/"buy" as the disambiguating words that let it resolve directly.
  Verified 9/9 bare phrasings ask, both qualified phrasings ("current plan" -> PROFILE, "plans I can
  buy" -> OFFERS) resolve directly, and the full 37-check matrix still passes.
- ~~Follow-up clarification turns landing under the 0.80 threshold~~ — **resolved 2026-09-03**, it
  was three things: (1) the model reported its leading guess as `intent` (low confidence) and only
  listed the *other* reading in `possible_intents`, so PROFILE silently dropped out of the
  candidate set — `build_router_result` now merges it back in; (2) added
  `INTENT_FOLLOWUP_CONFIDENCE_THRESHOLD=0.60` used only when candidates are present (a 2-way pick
  is an easier call than open classification); (3) the plan's own canonical phrases are now
  few-shot examples in `SYSTEM_PROMPT`, which stopped "show my details" wobbling — gpt-5 models
  run at temperature 1 with no override, so borderline phrases vary run to run without anchors.
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
