# Requirements status

Maps the MTN AI Assistant feature-requirement tracker to what actually exists in **this** build
(`telecom-assistant`, the India-market POC) — checked against the real code, not assumed from the
tracker's own "Completed" column, which describes MTN's separate production system (orchestrator +
billing agent, isiZulu/Xhosa/Sotho/Afrikaans, Azure AI Foundry/APIM). The two systems share almost
no code, so a "Completed" there does not imply "Completed" here — every status below was checked
directly against this repo.

| ID | Feature | Priority | Status here | One-line reason |
|----|---------|----------|-------------|------------------|
| F-001 | Natural Language Chat | MUST | **Done** | `/api/chat` takes free text, LLM classifies intent — no command syntax anywhere. |
| F-002 | Suggested Quick Actions | MUST | **Done** | 6 starter chips now, one per tool (`BALANCE`/`PROFILE`/`DEVICE_DETAILS`/`OFFERS`/`PURCHASE_HISTORY`) plus a COMPLEX showcase ("Am I eligible for 5G?"). Still fixed at load, not contextually regenerated after — acceptable for POC scope. |
| F-003 | Context-Aware Conversation | MUST | **Not started** | Confirmed by reading every LLM call site: only the current message is ever sent, no history array — a fact already established while designing the Cosmos DB work. Entities from turn N are gone by turn N+1, except the one narrow clarification follow-up case. |
| F-004 | Persistent History | MUST | **Not started (in progress)** | Cosmos DB account being provisioned now — see `PROGRESS.md`. |
| F-005 | Typing Indicator | MUST | **Done** | Animated `.typing` dots in both chat and voice (`addTyping()` / voice's pending-bubble dots in `index.html`). |
| F-006 | Rich Message Rendering | MUST | **Not started** | Every response is plain text. No card, table, image, chart, or PDF rendering anywhere in `index.html`. |
| F-007 | Smart Follow-Up | MUST | **Done** | The clarification flow (Phase 5/6) is exactly this — one focused question, never guesses. |
| F-008 | Personalised Greeting | SHOULD | **Not started** | No opening message at all — the thread starts empty except the 4 starter chips. Nothing greets by name/status. |
| F-009 | Voice-to-Text Input | SHOULD | **Done** | Mic capture + live transcription work end-to-end (`gpt-live-transcribe`). UI now shows a real animated **waveform** (40 smoothed, mirrored canvas bars) instead of the earlier single-bar level meter. Word-accuracy not formally measured, but the acceptance criteria's UI ask is met — the same nuance MTN's own tracker flagged as still-missing on their build. |
| F-010 | Text-to-Speech Output | COULD | **Different feature, not this one** | Voice *mode* is fully spoken (Realtime API) — but that's a separate live conversation, not a per-message speaker icon that reads an existing *text* chat bubble aloud with pause/resume. That specific interaction doesn't exist. |
| F-011 | Multi-Language Support | SHOULD | **Done (POC scope)** | Voice has real client-driven language detection/switching (Hindi/Telugu/Tamil/English), verified live repeatedly. Marked complete for this POC's scope — voice-only, Indian languages — rather than MTN's target set (Zulu/Xhosa/Sotho/Afrikaans), which is a different market and not this build's target. Chat text itself stays English-only. |
| F-012 | AI Response Feedback | MUST | **Not started** | No thumbs up/down anywhere, no feedback storage. |
| F-013 | Human Agent Escalation | MUST | **Not started** | No escalation path, no "Talk to Agent," no agent-to-agent routing — this POC has exactly one agent surface (the router + tools), nothing to hand off to. |
| F-014 | Attachment Support | SHOULD | **Not started** | No upload UI, no endpoint, no blob storage. See below for what it'd take. |
| F-015 | Real-Time Notifications | SHOULD | **N/A** | MTN's own tracker rejected this as out of scope for the AI layer (engineering/push-infra concern) — same is true here; no notification infrastructure exists or is planned. |
| F-016 | Conversation Search | SHOULD | **Not started** | Blocked on F-004 — nothing to search until history exists. |
| F-017 | Chat Personalisation | MUST | **Partial** | See below. |
| F-018 | Omnichannel Continuity | SHOULD | **Not started** | Blocked on F-004, and structurally out of scope beyond that — this POC only has a web channel; no WhatsApp/RCS/app integration exists to be continuous *with*. |
| F-019 | Session Recovery | MUST | **Not started** | Blocked on F-004 — a page reload today loses the conversation entirely. |
| F-020 | Accessibility Features | MUST | **Partial** | Light/dark theme is real and WCAG-contrast-checked (system default, manual toggle). Broader AA coverage isn't: only 2 `aria-*` attributes exist in the whole page (the theme control), no deliberate keyboard-nav pass, no large-text mode, screen-reader support unverified. |
| F-021 | Voice to Voice (English + regional language) | MUST | **Partial** | English/Hindi/Telugu/Tamil work live, verified repeatedly. Not isiZulu specifically — different market — and worth knowing precisely *why* it wouldn't work even if asked to: our language-switch logic detects language by Unicode script block, and isiZulu is Latin-script like English, so the detector would silently classify spoken Zulu as English rather than recognizing it, even before asking whether the underlying model can produce it. |
| F-022 | Voice Clone / Dialect | MUST | **Not started — contradicts a deliberate choice already made** | The realtime voice is intentionally hardcoded to one fixed voice (`alloy`) that never varies per request or customer, specifically to avoid the "voice keeps changing" bug reported earlier. Voice cloning would reverse that decision, not extend it — a real design conversation, not just unbuilt work. |

## F-014 — Attachment Support (SHOULD)

No attachment icon, file picker, or camera capture in `app/static/index.html`; no upload endpoint
in the backend; no Azure Blob Storage (or any storage) wired up. No decision made yet on what
happens to an uploaded file once received — forwarded to a vision-capable model, stored and just
referenced in the transcript, or handed to a human (there's no human-handoff path at all, see
F-013). Would need: a `POST /api/chat/attachment` endpoint, a Blob Storage account/container
(same ask-your-admin shape as Cosmos DB), and frontend upload UI (icon + picker + preview, 10MB
cap, PNG/JPG/PDF/HEIC).

## F-017 — Chat Personalisation (MUST)

What already works, live, today:
- Every answer is grounded in the *real* fetched account data (device, plan, balance, offers) —
  never generic.
- The COMPLEX/LangGraph advisory path (`app/services/complex_flow.py`) reasons over the specific
  customer's own data for judgment calls — e.g. "should I get roaming for my trip to Vizag" checks
  their actual plan and correctly reasons Vizag is domestic, so roaming isn't needed.
- The offers template (`app/services/response.py`) surfaces the telecom API's own `isPersonalized`
  and `isEligible` flags per offer when the API sets them.

**How to test:** ask "should I get roaming to Vizag" or "am I eligible for 5G" — the answer reasons
from that specific account's real plan/device. Ask for offers and look for "(personalized for you)"
/ "(not eligible)" tags.

What's missing: no tone adaptation, no recommendation logic beyond what the telecom API itself
already flags, and nothing based on interaction history — that's impossible until F-004 lands, since
there's no memory across sessions yet.
