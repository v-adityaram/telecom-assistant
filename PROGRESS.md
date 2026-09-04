# Progress

Tracks where this build stands against `docs/telecom_ai_assistant_implementation_plan.md`.
Read that file first for the full architecture and rules — this file is just status + open decisions,
so a session on any machine can pick up where the last one left off.

## Where things stand (2026-09-04, updated)

**Update 29 — Self-hosted TURN relay (coturn), to fix voice on TCS/Zscaler-managed laptops.**
Root-caused via a HAR capture + direct testing: voice fails specifically on TCS-managed laptops
(21s stuck at `ice checking` then `ice disconnected`/`connection failed`) but works fine on
personal laptops and phones on the same networks. Confirmed this session as almost certainly
Zscaler's client agent (installed on TCS-managed devices specifically, travels with the device
regardless of network — already proven earlier by a phone-hotspot test that didn't help) blocking
outbound UDP, which is what WebRTC/STUN needs. **STUN cannot fix this** — it only helps discover a
path through a *normal* NAT, not route around a network that blocks UDP outright.
**Fix: a self-hosted TURN relay**, chosen over a managed/paid TURN service (Twilio, Metered, etc.)
per direct user preference — free, runs on the existing VM, no new vendor.
- **How it works**: the caller's browser opens exactly one outbound TCP/TLS connection to *our own*
  TURN server on port 5349 — indistinguishable from ordinary HTTPS to Zscaler, so it gets through.
  The VM then relays outward to Azure's Realtime API over UDP itself, which is unrestricted (no
  corporate agent runs on the Azure VM).
- **Credentials are ephemeral, mirroring the existing Azure OpenAI pattern** (`realtime.py`'s
  short-lived token) — never a standing secret in browser JS. `app/services/turn_credentials.py`
  implements coturn's standard REST-API credential scheme (HMAC-SHA1 of an expiry timestamp under a
  server-only shared secret); `POST /api/voice/session` (`app/api/voice.py`) now returns a `turn`
  field (`null` when `TURN_SHARED_SECRET`/`TURN_DOMAIN` aren't configured — chat/voice behave
  identically either way, same no-op-when-unconfigured pattern as Cosmos). Frontend
  (`app/static/index.html`) adds it to `RTCPeerConnection`'s `iceServers` alongside the existing
  STUN entry when present.
- **Deployment** (`deploy/setup_vm.sh`): installs `coturn`, points it at the *same* Let's Encrypt
  cert already obtained for the app (copied into a coturn-owned location since coturn's user can't
  read `/etc/letsencrypt` directly — refreshed automatically via a
  `/etc/letsencrypt/renewal-hooks/deploy/` script on every renewal, not just at setup time), narrow
  relay port range (49160-49200 — ~40 concurrent calls, keeps the NSG footprint small), and
  auto-sets `TURN_DOMAIN` in `.env` to match `PUBLIC_DOMAIN` so it's never a second value to keep in
  sync by hand. Entirely opt-in: skipped (and coturn disabled if previously enabled) whenever
  `TURN_SHARED_SECRET` is blank in `.env`.
- **What the user still needs to do manually**: (1) set `TURN_SHARED_SECRET` in the VM's `.env` to
  a real random string (not auto-generated — a deliberate secret you choose), (2) add an inbound
  NSG rule for **TCP 5349** (the relay port range needs no inbound rule — that traffic is VM-
  initiated outbound UDP to the real peer, and NSGs are stateful, so return traffic is allowed
  automatically).
- **Staged, not the maximal version, on purpose**: this ships plain TURN-over-TLS on port 5349, not
  the full SNI-multiplexed port-443 approach (sharing 443 with nginx via `ssl_preread` routing,
  which would make TURN traffic indistinguishable from the app's own HTTPS too, for networks that
  block literally everything except 80/443). Deliberately not built yet — it's a much bigger,
  riskier nginx refactor, and it's not yet confirmed that Zscaler blocks 5349 specifically (it may
  only be blocking UDP, in which case this simpler version is sufficient). **Test on a TCS laptop
  after this deploy before investing in the 443-multiplexed version** — only build that if 5349
  alone still doesn't get through.
- Not yet retested live end-to-end (needs a real TCS laptop + the NSG rule added) — unit tests only
  cover the credential-generation logic and the `/api/voice/session` response shape.

**Update 28 — Two more real frontend bugs, both fixed.**
1. **"Please wait — connecting your microphone…" toast required scrolling up to see, in a
   conversation that had scrolled down.** Root cause: `.voice-overlay` was `position:absolute;
   inset:0` with `.thread` — the *scrollable* message container — as its containing block.
   Absolutely-positioned children scroll out of view with their scrolling ancestor's content;
   they don't stay pinned like `position:fixed`/`sticky` would. Fixed by introducing
   `.thread-wrap` (a new non-scrolling `position:relative` parent — only `.thread` inside it
   scrolls) and moving `.voice-overlay` to be anchored to that instead, as a sibling of `.thread`
   rather than a child. Now always visible over the thread area regardless of scroll position.
2. **The voice stop button rendered as an oval, not a circle.** `.icon-btn` had explicit
   `width/height:36px` + `border-radius:50%`, which should be a perfect circle — but no
   `flex-shrink:0`, so a cramped flex row (the voice bar, competing with the level meter for
   space) could compress its width below 36px while height stayed put. Fixed with
   `flex-shrink:0`, plus sized down `36px -> 32px` (and its icon `18px -> 16px`) per direct
   request. Applies to *every* `.icon-btn`, not just the voice stop button (sidebar toggle,
   theme toggle) — consistent sizing, not a one-off patch.
Not yet re-verified live on the actual reported devices.

**Update 27 — Recents sidebar: rows clipping the bottom of their own text (descenders like the
tail of "p" going missing), same root cause class as Update 22.** `.recents-list` is a
`flex-direction: column` container; its children (`.recent-item` buttons) never had
`flex-shrink: 0`. Once enough conversations existed that they didn't all fit in the list's `200px`
height, the flex column **compressed each row shorter than its natural text height** instead of
properly overflowing/scrolling — clips a slice off the bottom of every row's text, not just an edge
row. Fixed: `flex-shrink: 0` added to `.recent-item` (the actual fix — forces the container to
scroll instead of squeezing children), plus `line-height: 1.4` for more natural breathing room and
`.recents-list` height raised `200px` -> `280px` per direct user request for more visible rows.
Not yet re-verified live with a real conversation list at that length.

**Update 26 — iPhone-specific echo: assistant's own voice leaking into the mic, not seen on
Android.** Direct user report: only some iPhones (16 confirmed), Android unaffected. Root cause is
most likely Safari/iOS WebKit's WebRTC echo-cancellation being less reliable than Chrome's
(especially over the loudspeaker, and especially compared to Android Chrome's more mature/consistent
AEC implementation) — a known, longstanding platform gap, not really fixable purely from a web app;
native apps get far more control over this via `AVAudioSession`. One real contributing factor found
in this app's own code and fixed regardless: `remoteAudioEl` (the assistant's audio) was a detached
`new Audio()` element, never attached to the DOM — WebKit's audio-session handling has documented
inconsistencies for playback outside the document. Now created hidden but DOM-attached (`playsInline`
set too, relevant on iOS), and properly cleaned up (`.pause()`, `srcObject = null`, `.remove()`) in
`teardownVoice()` so repeat calls don't leak elements. **Set realistic expectations**: this may
reduce the iPhone-specific leak but is unlikely to fully eliminate it — the practical, reliable fix
for affected iPhones is headphones/earbuds (removes the acoustic speaker->mic leak path entirely,
making AEC quality moot). Not yet retested live on an affected iPhone 16.

Large session — Cosmos DB actually provisioned and wired up end-to-end, real conversation
memory, a new purchase-demo intent, a full frontend redesign, three real voice bugs found and
fixed, and the ChatGPT-style "Recents" sidebar built. Everything below was verified live against
the real Azure OpenAI + Cosmos DB + telecom API, both locally and on the deployed VM, not just
unit-tested — see each entry for how.

**Redeployed and confirmed live (2026-09-04)**: all of the above is running on the VM. The VM's
`.env` (never in git) currently has two manually-tuned values that differ from `.env.example`'s
documented defaults — check the VM's actual `.env` before assuming these match the repo:
`INTENT_CONFIDENCE_THRESHOLD=0.90` (default `0.80`) and `REALTIME_VAD_THRESHOLD=0.8` (default
`0.7` — this was the idle baseline for Update 19's dynamic scheme; see the next entry, it's since
moved to `0.9` in code). `COSMOS_CONNECTION_STRING` is also set, so conversation memory/Recents
are actually active on the VM, not just no-op'd.

**Update 25 — VAD idle threshold raised 0.8 → 0.9, unifying it with the speaking threshold.**
Direct user report: background voices behind the caller were still triggering turns during normal
listening (not just while the assistant was talking, which `0.9` already covered per Update 19).
`VAD_THRESHOLD_IDLE` in `app/static/index.html` raised from `0.8` to `0.9` to match
`VAD_THRESHOLD_SPEAKING` — both states now equally strict. **Deliberately not a decibel/volume
gate** — considered and rejected by the user themselves: a hard loudness cutoff risks clipping the
start/end of their own quieter syllables along with background talkers, not just filtering the
latter. The VM's `.env` still has `REALTIME_VAD_THRESHOLD=0.8` (the mint-time initial value,
overridden live once `setVadThreshold()` runs) — bump that too on next redeploy for consistency
from the very first moment of a call, though the dynamic override makes this a minor gap, not a
functional one. Not yet retested live against real background chatter.

**Update 15 — Cosmos DB provisioned; conversation memory (F-003) built and wired in.**
Account `telecom-assistant`, database `telecom-poc-db`, container `conversations`, partition key
`/mobileNumber` (confirmed correct in Data Explorer before any data was written — this is the one
field that can never change after container creation). `app/services/conversation_store.py` is the
whole persistence layer: `is_enabled()`, `upsert_conversation()`, `get_conversation()`,
`list_conversations()`, `delete_conversation()` — every function no-ops safely if
`COSMOS_CONNECTION_STRING` isn't set, so chat/voice behave identically whether or not this is
configured. `session_id` (already sent by the frontend on every turn) doubles as the Cosmos
`conversation_id` — no new identifier needed. `app/api/chat.py` loads that conversation's prior
messages before routing and persists the new turn after answering, for every response type
(answer, clarification, error) via `asyncio.to_thread()` (the Cosmos SDK is synchronous; without
this it would block the event loop on every turn). History (capped to the last 20 messages) is
threaded into `app/services/llm.py::classify_intent()`, `app/services/complex_flow.py`'s answer
node, and `app/services/purchase_flow.py` — real prior turns as actual `{role, content}` messages
in the `messages` array, never folded into the system prompt string. Verified live: a multi-turn
conversation asking balance → device → "what all did I ask till now" correctly summarized real
history, both locally and on the VM (one genuine test-methodology bug found along the way, not a
code bug — a crashed test script left a half-written turn in Cosmos, and a rerun with the same
session id correctly *added to* it rather than losing it, which is exactly the durability this was
built for).

**Update 16 — Router taught to use that history for single-intent turns too, not just COMPLEX.**
`app/router/intent_router.py::route_intent()` and `classify_intent()` now also take `history`.
Needed because F-003 initially only gave history to the COMPLEX flow — genuine follow-ups that
don't obviously need multi-tool COMPLEX handling ("why is my data low" right after balance was
shown, "how good is that offer", "details") were still falling into the generic clarification
fallback since the *classifier itself* couldn't see what was said two turns ago. Fixed with a
general rule in `llm.py`'s prompt (judge by meaning, not exact wording — informal phrasings count
the same as the given examples) rather than one-off string matches. **Tested for real
generalization, not just the literal examples fed into the prompt**: two rounds of live testing
with wording never used anywhere in the prompt ("that seems like barely anything left, how come",
"grab me the international roaming one", "worth getting?", "put me down for the weekend pack",
"feels like it vanished fast, any idea why") — most generalized correctly. Two real gaps found and
left as known, not silently claimed fixed: "so what am I actually getting" still misfires to
clarification sometimes, and once (asking "elaborate" about a just-completed demo purchase) the
COMPLEX answer node contradicted its own prior turn, claiming it hadn't actually captured the
order. Consistent with the temperature-1 wobble already documented below — not fully eliminable by
more prompting, a POC-level limitation worth knowing about, not chasing indefinitely.

**Update 17 — BUY_OFFER: a new demo purchase intent.** `app/services/purchase_flow.py` +
`BUY_OFFER_INTENT` in `app/router/confidence.py` (special-cased like `COMPLEX_INTENT` — not a
`TOOL_REGISTRY` entry, since it's not a real telecom-API lookup). On a match it always **re-fetches
real, current offers first**, then asks the model only to pick *which* offer id is meant
(structured JSON output, matched against history so "buy the 2nd one" resolves against whatever
offers list was shown earlier) — the confirmation text itself (name, price) is built
deterministically from that real data afterward, never freeform LLM text, so a price can never be
invented. Ends with a disclosed dummy payment link, matching the reference design the user showed
("this is not a real purchase"). Verified live: both an ordinal reference ("buy the 2nd one") and a
direct name ("the weekend entertainment pack") correctly resolved to the right real offer, on both
the fast path and the router's now-history-aware classification.

**Update 18 — Frontend redesign: moved off the ChatGPT look entirely.** New warm gold/amber palette
(light + dark, WCAG-checked — AA minimum, mostly AAA) replacing the neutral gray/black scheme;
gold header band instead of a blended-in topbar; warmed sidebar tone instead of near-black; the
empty-state greeting is now a gold-bordered card with a folded-corner accent instead of plain
centered text; starter chips became a 2×3 "Quick actions" card grid (one per tool, title + subtitle
+ arrow) instead of pill buttons; composer restructured into separate labeled "Talk" / input /
"Send →" pills instead of one icon-only ChatGPT-style bar. Real bugs found and fixed while building
this, not just cosmetic: the dark-mode theme-toggle icon was unreadable (forced to a color meant
only for the gold header band, invisible against the button's own dark surface); the quick-action
grid overflowed off-screen on narrow viewports (classic CSS Grid issue — a grid item's default
`min-width:auto` lets text force a track wider than available space; fixed with
`minmax(0, 1fr)` + explicit `min-width:0` + ellipsis truncation, confirmed via direct
`scrollWidth`/`innerWidth` measurement, not just a screenshot); a leftover hardcoded blue/purple
gradient on the brand dot/avatar was replaced with the new accent gradient; a latent bug
(`var(--fg)`, a token that never existed) in the voice-overlay CSS was fixed to `var(--text)`.

**Update 19 — Three real voice bugs found and fixed.**
1. **The "Conversation already has an active response in progress" API error and duplicate
   spoken answers**: `handleFunctionCall()`'s `response.create` (after a tool call) was completely
   unguarded, while the language-switch turn logic already serialized itself. When a tool-call
   continuation raced against a response Azure hadn't yet confirmed finished (a real,
   network-timing-dependent race — explaining why it was intermittent, not constant), the unguarded
   call collided and got rejected, sometimes leaving a turn answered twice. Fixed by routing *every*
   `response.create` in `app/static/index.html` through one `whenResponseFree()` queue. Proven
   correct by simulating the exact race in an isolated Node script (not just reasoning about it).
2. **No real interruption/barge-in**: `input_audio_buffer.speech_started` updated the UI but never
   actually stopped the assistant's in-progress response. Now sends `response.cancel` when the
   caller starts talking mid-response, and drops anything queued behind that now-dead response so
   nothing tries to continue it afterward.
3. **Dynamic VAD sensitivity**: `turn_detection.threshold` is now pushed to `0.9` while the
   assistant is speaking (so its own audio/echo doesn't false-trigger a self-interruption, while a
   genuinely louder deliberate interruption still clears it) and back to `0.8` the instant it's
   idle (maximizing responsiveness when nothing is competing acoustically), via live
   `session.update` calls on `output_audio_buffer.started`/`stopped`.
   All three verified by simulating the exact event sequences in an isolated script (queueing,
   draining, threshold changes, no redundant sends) — genuine WebRTC/microphone behavior still
   needs a real call to confirm end-to-end, which this session's environment can't drive.

**Update 20 — Transcription sync research (not built, informational).** Confirmed via current Azure
docs: the conversational model (`gpt-realtime-1.5`) can never itself serve as the transcription
model — Azure's `input_audio_transcription.model` architecturally requires a separate dedicated
transcription-model deployment, by design, not a gap on our end. But Azure now documents a
dedicated **"transcription session" type** (`session.type: "transcription"`) built specifically for
streaming transcript *deltas* (word-by-word), unlike the "final text only after the utterance ends"
behavior this app is stuck with today via the bolted-on `input_audio_transcription` in the
voice-agent session. Getting real synced captions would mean a **second parallel WebRTC
connection** just for captions — genuine new scope, not a quick config change. Not started; worth
scoping properly before committing to it.

**Update 21 — F-004 (Persistent History) sidebar: built, the "Recents" panel now works.**
`app/api/conversations.py` — `GET /api/conversations?mobile_number=` (list, newest first,
auto-derived titles) and `GET /api/conversations/{id}?mobile_number=` (full message history, 404 if
missing), both backed by the Cosmos layer from Update 15. Frontend: a real Recents section replaces
the old empty sidebar spacer — populates on load and after every sent message, click any item to
replay it into the thread and **continue that same conversation** (same `session_id`, so new
messages append to its real Cosmos history rather than starting fresh), active item highlighted,
switching the account number refreshes the list (conversations are scoped per number — the
partition key). Verified live end-to-end: created real conversations, listed them, clicked one, and
watched a full multi-turn conversation from earlier in the session replay correctly in order.
**Known simplification, not a bug**: replayed messages don't show their original intent pill
(Cosmos only stores `{role, content}`, not the tag) — renders as plain text on reload.

**Update 22 — Sidebar layout bug: Recents collapsing to empty at 100% browser zoom.** Real bug, not
cosmetic: `.recents-list` used `max-height` inside a flex column that also scrolls — a CSS gotcha
where a flex item's automatic minimum height resolves to 0 once any ancestor's `overflow` isn't
`visible`, which the sidebar's own `overflow-y:auto` (added earlier the same session to fix a
different cramping issue) triggered at some viewport heights but not others, explaining why 75-80%
zoom looked fine but 100% didn't. Fixed by giving `.recents-list` a **fixed height (200px) with
`flex-shrink:0`** instead of a flexible one — sidesteps the collapse entirely regardless of zoom or
viewport size. Also removed the sidebar's redundant "Appearance" System/Light/Dark segmented
control (the top-right theme toggle already covers it) per direct request, freeing real vertical
space and simplifying `applyTheme()`. Stress-tested at 600px/650px/700px/800px viewport heights —
Recents shows real, readable items every time now, never empty. Mobile's `@media (max-width:860px)`
block was not touched.

**Update 23 — Voice language detection: fixed code-switching, not just this one phrase.** Real bug
found from a live phone call: the caller said "इसमें कनेक्शन currently active" (genuine
Hindi-English code-switching — Hindi speakers routinely borrow English nouns mid-sentence; this is
not broken speech, it's how the language is actually spoken) and the assistant replied in English
instead of Hindi. Root cause: `detectLanguage()` in `app/static/index.html` picked whichever script
had the *most matched characters* — and the borrowed English words ("connection", "currently",
"active") routinely outnumbered the Hindi grammatical scaffolding by raw character count. Fixed
generally, not with a special case for this phrase: Indic scripts are now checked *before* English,
and any of them clearing the existing 5-character threshold wins outright regardless of how much
English is mixed in — English is only chosen when no Indic script clears its threshold at all.
Verified against 10 cases before deploying, including the exact reported line, two more real lines
from the same transcript, a **Telugu** code-switch (proving this isn't Hindi-specific), full-English
and full-Hindi sentences, and every filler case that must not falsely flip language — all 10 pass.
**One language question from a later call — asking to continue in Malayalam when the caller reports
never having spoken Malayalam — was left unresolved.** Couldn't reproduce or diagnose it from a
screenshot alone (unlike the other three items in Update 24 below, which were each proven with a
concrete before/after test); asked the user to capture the debug drawer log next time it happens
rather than guess a fix. Worth checking first if it happens again.

**Update 24 — Three more real bugs from continued live phone testing, all fixed and verified live
(not just reasoned about), none of them silently claimed done.**
1. **"Cancellation failed: no active response found" showing as a scary red error.** A benign race
   from the Update 19 interruption fix: `response.cancel` fires the instant speech is detected, but
   the response it meant to cancel can finish naturally a moment before that reaches the server —
   nothing left to cancel. Now matched by message text and logged quietly instead of surfaced as a
   `voice error` chat bubble.
2. **Chat thread not resetting when the account number changes.** Recents correctly scoped to the
   new number, but the visible thread kept showing the old number's messages — misleading, since
   Cosmos partitions by `mobileNumber` so that conversation isn't even reachable under the new
   number. `saveMobileNumber()` now calls the same `startFreshConversation()` the "New chat" button
   uses, but **only when the number actually changed** (tracked via `lastMobileNumber`) — re-saving
   the same number is a no-op, verified both cases directly with a synthetic before/after check
   rather than just reading the code.
3. **Voice conversations never appearing in Recents at all — a real wiring gap, not a subtle bug.**
   Text chat persists through `/api/chat`; voice audio goes straight from the browser to Azure and
   never touches our backend at all, so nothing was saving those turns to Cosmos. Added
   `POST /api/conversations/{id}/turns` (`app/api/conversations.py`) and the browser now calls it
   after each spoken exchange (caller transcript + assistant's reply, or a placeholder if
   transcription failed) — `chatSessionId` is now generated up front if a voice call starts one
   fresh. Verified by dispatching real events through the actual `onRealtimeEvent()` handler (not a
   mock) against the live server and reading the write back from Cosmos — both locally and on the
   VM.

**Update 7 (handoff — this session is moving to a different laptop):** `REALTIME_VAD_THRESHOLD`
was pushed to `0.7` (Update 6), tested live, **still not enough** — loud background noise still
triggered false utterances. Escalated to **`0.9`**, set directly in the VM's `.env` via `nano` over
Serial Console (`sudo systemctl restart telecom-assistant` to apply) — **this value is NOT in git**,
`.env` is gitignored by design (never commit secrets/config), so `deploy/setup_vm.sh` will never
touch or overwrite it. If a future redeploy seems to "lose" this tuning, it hasn't — check the VM's
actual `.env`, not `.env.example`'s `0.7` default, before assuming something regressed. **Result of
the `0.9` test was not yet reported back when this session ended** — that's the immediate next thing
to check with the user. If `0.9` still isn't enough, VAD-threshold-tuning alone is very likely not
the answer and the mic/environment itself (a real noise-cancelling headset, not laptop speakers/mic)
should be tried before adding more software levers. Two substantial architecture discussions from
this session exist ONLY in chat, not in any code yet — see **Open architecture discussions** below;
read that section before starting the Cosmos DB / conversation-memory work if the user brings it up
again, since real conclusions were already reached about the *design*, not just "should we."

**Update 6:** the rapid-language-switching in Update 5's log turned out to be the reporter
deliberately testing the language-switch feature, not a symptom — retracted that part of the
diagnosis. The real remaining complaint is background noise (confirmed loud, confirmed real noise
not a misread) still triggering false utterances even with `noise_reduction` + STUN + the 750ms
`silence_duration_ms`. Added `REALTIME_VAD_THRESHOLD` (`app/config.py`, wired into
`_session_config()` in `realtime.py`) — server_vad's `threshold` was hardcoded at the API's `0.5`
default, which is moderate sensitivity, clearly not enough for a loud environment. Now configurable
via `.env`, defaulted to `0.7`. Made configurable rather than hardcoded (unlike the `750ms` change)
specifically because this needs real-environment tuning that will likely take more than one pass —
raise it further via `.env` + `sudo systemctl restart telecom-assistant` (no redeploy needed) if
still too sensitive; lower it if genuine quieter speech starts getting missed. Not yet retested live.

**Update 5:** `noise_reduction` + STUN (Update 3) were deployed and retested live — did NOT fix it.
A real voice session still showed constant false triggers: rapid language-switching (English ->
Telugu -> Malayalam -> Telugu -> Hindi -> English inside two minutes), garbled multi-script
gibberish in single utterances ("E tem मेरे", "أنت بتسجل quello"), and responses firing only
seconds apart. Raised `silence_duration_ms` 500ms -> 750ms in `_session_config()`
(`app/services/realtime.py`) per direct user request ("it's answering too quickly") — at 500ms a
brief pause or noise gap was enough to prematurely end a turn, fragmenting one utterance into
several. **This alone is very unlikely to fully fix it** — the density and severity of what was
observed (multiple full responses per minute, scripts mixing within one transcript) looks more
like a genuine feedback/echo problem (mic picking up the assistant's own speaker output) than pure
timing. Untested hypothesis, not yet confirmed: ask the reporter to retest once with headphones —
if the problem mostly disappears, it's echo, not noise or timing, and `echoCancellation` on
`getUserMedia` alone isn't fully handling speaker/mic feedback in this environment. If it persists
even with headphones, `threshold` (currently 0.5, unchanged) is the next lever — raising it reduces
sensitivity to background volume specifically, separate from timing.

**Update 4:** replaced the self-signed TLS cert with a real, browser-trusted Let's Encrypt one.
Public CAs never issue certs for a bare IP, so `deploy/setup_vm.sh` now derives a free sslip.io
hostname from `PUBLIC_IP` (`104.211.224.38` -> `104-211-224-38.sslip.io`, resolves with zero DNS
setup) and obtains a cert for it via the HTTP-01 webroot challenge — a `PUBLIC_DOMAIN` env var
overrides this if a real owned domain is ever pointed at the VM instead. First run does a brief
http-only nginx bootstrap (the real config can't start yet — it points at a cert that doesn't exist
until the challenge succeeds); every run after that is a no-op since the cert already exists.
Renewal is automatic via certbot's own systemd timer, with a `--deploy-hook` so nginx actually
reloads the renewed cert (it caches the loaded cert in memory otherwise). nginx never needs to stop
for either issuance or renewal — webroot, not standalone. Visiting the app is now
`https://104-211-224-38.sslip.io/`, not the raw IP. Not yet re-verified with an actual redeploy on
the VM — do that before calling this closed, and if the ACME challenge fails, check that port 80 is
still reachable from the internet (it was, per the NSG rules recorded in the deployment notes below).

**Update 3:** added Realtime API `noise_reduction` (`audio.input.noise_reduction`, mode set via
`REALTIME_NOISE_REDUCTION_MODE`, default `far_field`) to `_session_config()` in
`app/services/realtime.py`, plus explicit `echoCancellation`/`noiseSuppression`/`autoGainControl`
constraints on the frontend's `getUserMedia` call (`app/static/index.html`, was bare `{ audio: true }`).
Motivated by a live debug log showing background noise occasionally tripping `server_vad`'s energy
threshold on its own and getting transcribed as speech in a random/wrong language (no caller actually
spoke). Not yet re-verified live against real background noise — do that before calling this closed,
and reach for `near_field` instead of the `far_field` default if the caller is on a headset rather
than a laptop/desk mic.

**Update 2:** two live-testing findings from a phone session, both fixed:
- **Chat gave a misleading answer when the message named a different phone number**
  ("what's the device of 9999900004" while signed in as `...0003`) — it silently answered with the
  *signed-in* account's own data, phrased as if it had answered about the other number. The backend
  was always correctly ignoring the message-stated number per the security rule (never let the model
  pick the account) — the bug was answering at all instead of saying so. Fixed in `app/api/chat.py`:
  `_mentions_different_account()` regex-detects a 10-digit (or 12 with a "91" prefix) number in the
  message that doesn't match the authenticated `mobile_number`, and short-circuits to a plain decline
  *before* the router or any tool runs — no LLM call spent on it either. Deliberately narrow (10/12
  digit runs only) so a 15-digit IMEI or a 4-6 digit OTP mentioned in a message doesn't false-trigger.
  Tests: `test_message_naming_a_different_number_declines_without_router_or_tool_call`,
  `test_message_naming_the_same_number_is_not_treated_as_different` in `tests/test_chat_api.py`.
- **Voice: audio played immediately but the transcript bubble didn't appear for ~1-3s after**, since
  Azure's Realtime API produces the full transcript only at `response.output_audio_transcript.done`,
  well after `output_audio_buffer.started` (no streaming deltas — see the known-limitations note
  above). Chat already showed typing dots for its own latency; voice showed nothing. Fixed in
  `app/static/index.html`: `output_audio_buffer.started` now immediately adds an assistant bubble
  with the same `.typing` dots chat uses (tracked in `pendingVoiceAssistantMsg`), and
  `response.output_audio_transcript.done` replaces the dots with the real transcript instead of
  creating a new bubble. If the caller barges in before a transcript ever arrives, the stale dots
  bubble is removed on the next `input_audio_buffer.speech_started` rather than bouncing forever.
  This doesn't reduce the actual delay (that's an Azure API constraint) — it just gives the same
  "working on it" feedback chat already had. Not yet re-verified live on a real call with barge-in —
  do that before calling this closed.
- **Voice stuck on "Requesting microphone…" then ICE disconnected/connection failed, on some laptops
  only.** `RTCPeerConnection()` in `app/static/index.html` had zero ICE servers configured — no STUN,
  no TURN. Without STUN, the browser can only gather local ("host") candidates, which only happen to
  connect across NATs that are permissive enough (explains "works on some laptops, not others" — the
  failing ones are presumably on stricter corporate NATs/firewalls). Added a public STUN server
  (`stun:stun.l.google.com:19302`). Not yet re-verified on a previously-failing laptop — if it still
  fails after this, the network is very likely blocking outbound UDP entirely (common on
  Zscaler-style corporate proxies), which STUN can't fix — that needs a TURN relay (media relayed
  over TCP/443), a real infrastructure addition (self-hosted coturn or a paid TURN service) worth
  discussing with the user before building, not something to add speculatively.

## Where things stood (2026-09-03, end of prior session)

**All 10 plan phases are done and deployed.** Live at **https://104.211.224.38/** (self-signed
cert, accept the warning once). Redeploy: `cd ~/telecom-assistant && git pull && sudo ./deploy/setup_vm.sh`.

**Solid, verified repeatedly, not just once:**
- Chat: all 5 intents, typo tolerance, ambiguity → clarification, multi-turn follow-up resolution,
  scope-aware answers (broad question → full template, narrow question → precise synthesized
  answer), the COMPLEX/LangGraph fallback for multi-domain and advisory questions, security checks
  (model can't override the phone number, can't call arbitrary URLs), graceful error handling.
  `scripts/live_smoke.py` — 47 checks — is the regression net; run it after touching the router
  prompt, thresholds, templates, or `complex_flow.py`.
- Voice: WebRTC connects, mic capture confirmed via a live level meter, tool calls work, all 5
  telecom APIs reachable, barge-in/interruption works, caller transcription works
  (`gpt-live-transcribe`), the voice stays fixed (`alloy`, never drifts), language switching is
  client-driven and deterministic (see Phase 8 below), numbers are spoken in English regardless of
  sentence language, missing data (e.g. no customer name field) is reported honestly rather than
  a made-up excuse.
- Frontend: single dependency-free HTML file, light/dark theme with system default (WCAG-checked),
  mobile-responsive, debug drawer for exactly this kind of live debugging.

**Known limitations, not bugs to chase further right now:**
- gpt-5-series models run at temperature 1 with no override, so a small number of borderline chat
  phrasings occasionally wobble between runs even after prompt anchoring (documented per-case
  below). Real, low-frequency, not fixable by more prompting — it's inherent model variance.
- Azure's Realtime API never streams transcription deltas (confirmed via Microsoft support) — captions
  land after each utterance, not word-by-word. True live captions would need Azure AI Speech running
  in parallel; deliberately not started (bigger integration, discussed and declined for now).
- `gpt-live-transcribe`'s default quota is 10 requests/min; very rapid back-to-back voice turns could
  hit it (raise the quota in the portal if it shows up as a rate-limit `.failed` code).

**If picking this up fresh, read in this order:** the numbered Updates above this block (newest
first — Update 7 is the actual current state and says what's still pending) → **Open architecture
discussions** further below (Cosmos DB / conversation memory, and Realtime API vs Voice Live API —
real design decisions already reached in a prior chat, not yet built) → this section → the Phase 8
(Realtime Voice) entry below, which has the most hard-won detail (Azure quirks that cost real
debugging time — mint-time transcription failing, session.update replacing not merging, the
language-switching redesign) → the Phase 9/scope-aware entries if touching chat → `deploy/` if
touching infrastructure.

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
      collapsible debug drawer instead of the main thread. **Light/dark themes** (2026-09-03): the
      page was dark-only with hardcoded colors; every color now goes through a token, with light as
      the base palette and a `:root[data-theme="dark"]` override. A tiny inline script in `<head>`
      applies the stored choice (or the OS preference when none) before first paint so there's no
      flash; a System/Light/Dark control in the sidebar and a sun/moon button in the top bar both
      write `localStorage.theme` (System = key removed, so it keeps following the OS live). Mobile
      tweaks in the same pass: 16px composer input (stops iOS zoom-on-focus), safe-area bottom
      padding, full-width debug drawer, wrapping voice hint. Fixed a bug the same night: the
      theme-toggle button showed both the sun and moon icons stacked — `.hidden = true` is a no-op
      on `<svg>` elements (that property only exists on HTML elements), so the `[hidden]` CSS rule
      never matched; switched to `toggleAttribute('hidden', ...)`. **Account number save button**
      (2026-09-03): the field previously had no explicit save step or confirmation — typing just
      changed what the next request used, silently. Added a Save button beneath it that persists to
      `localStorage.mobileNumber` (restored on load, replacing the hardcoded sample default) and
      shows "Saved ✓" for 1.5s; Enter in the field saves too. Deliberately **omits**
      the docs' `?webrtcfilter=on` query param — that filter's allow-listed event set does not
      include `response.function_call_arguments.done`, which would silently break tool calling.
      Also added a live mic-level meter (Web Audio `AnalyserNode`) to the Voice panel, independent
      of Azure entirely — useful for isolating "browser isn't capturing audio" from "Azure isn't
      responding" if voice ever seems dead again. Tested with mocks: `tests/test_realtime.py`,
      `tests/test_voice_api.py`.
      **Caller transcription (captions) — enabled 2026-09-03**, and it was a fight; the details
      matter for whoever touches this next:
      - **True word-by-word live captions are not possible on Azure.** Microsoft support confirms
        Azure's Realtime API never emits `conversation.item.input_audio_transcription.delta`
        (OpenAI's own API does); Azure only sends the final transcript once a turn ends. So captions
        appear right after you stop speaking, not while you speak. Real live captions would need
        Azure AI Speech running in parallel on the same mic audio — a separate, bigger integration,
        deliberately not started.
      - **Requesting transcription at mint time fails.** Putting `audio.input.transcription` in the
        `client_secrets` payload made every turn emit `input_audio_transcription.failed` with
        `code=DeploymentNotFound`, even though the deployment name was verified correct in the
        portal. Known Azure issue. Fix: mint without it, then send a `session.update` over the data
        channel once connected — `create_realtime_session()` returns it as `post_connect_update`.
      - **`session.update` must carry `session.type`** ("Missing required parameter" otherwise, despite
        docs calling all fields optional) — and it appears to **replace nested objects wholesale
        rather than deep-merge**: sending only the transcription field reset the output voice to
        something other than `alloy`, which a user noticed as "the voice keeps changing". So
        `post_connect_update` re-states the *entire* session (instructions, tools, voice,
        turn_detection, transcription), built from the same `_session_config()` as the mint payload
        — single source of truth, nothing can drift between the two again.
      - **Model**: started with `gpt-4o-mini-transcribe` ($0.003/min) — worked, but rendered Hindi
        in Urdu script and mis-detected Telugu. `gpt-realtime-whisper` (the purpose-built model)
        isn't available on this subscription. Switched to **`gpt-live-transcribe`** (~$0.017/min,
        GA, one of the two models Microsoft documents for real-time transcription). Its default
        quota is only **10 requests/min** — each spoken turn is one request, so rapid back-and-forth
        can hit it; raise the quota in the portal if that shows up as a rate-limit `.failed` code.
      - Also transcription failures are **cosmetic only**: the voice model understands audio
        natively and answers correctly whether or not the caption succeeds (tool calls kept working
        through every `.failed` event).
      - Voice instructions also now ask for plain everyday spoken Hindi/Telugu/Tamil rather than
        formal "book" register — user feedback was that the literary phrasing was hard to follow.
      - **Language switching is client-driven (2026-09-03).** Left to infer, the model kept the
        *previous* turn's language when the caller switched (spoke Hindi, asked in Telugu, got Hindi
        — once even announcing "your first question was in Hindi, so I'll stay in Hindi"). A
        transcript-based hint didn't fix it because the transcript arrives *after* the answer has
        started, so on the switch turn the model obeyed a stale hint. Now, when transcription is
        on, the post-connect session sets `turn_detection.create_response=false`: the server commits
        each utterance but does not answer. The browser (`index.html`, "caller-language protocol")
        waits for the transcript, detects its script by Unicode block (Telugu/Tamil/Devanagari/
        Arabic-script Hindi/Latin…; fillers like "Yeah."/"हाँ" don't count), keeps a session
        language, and sends session.update with an explicit `CURRENT CALLER LANGUAGE:` line — on a
        switch, "answer in the new language, then ask whether to continue in it" — followed by
        `response.create`. One response at a time is enforced (a second trigger waits for
        `response.done`), and a 2.5s fallback timer answers even if the transcript never comes.
        Cost: ~1s extra per voice turn. Numbers (amounts, MB, dates, IMEI digits) are always spoken
        in English regardless of language, per user request. Without transcription configured none
        of this engages and the server auto-responds as before. Live test after: switches
        Hindi→Telugu→Hindi all landed in the right language; the "continue in X?" question was
        asked on 1 of 3 switches, so that instruction is now phrased as mandatory.
      - **Data honesty (2026-09-03)**: asked "what's my name", the model sometimes said "not in your
        account" (true — the profile API has no name field) and sometimes "can't share it for
        privacy/security" (invented — no such policy exists). The voice prompt now lists exactly
        what the profile contains and says absent data must be reported as "not available in what I
        can see", never as a withheld/policy matter, and never by asking the caller for their name.
      - **English as the starting default (2026-09-03)**: `voiceLang` now initializes to `'English'`
        (was `null`) instead of only being set once something was detected — a call that opens with
        a filler-strength utterance ("Hello.") now defaults to English rather than leaving the model
        to pick with no `CURRENT CALLER LANGUAGE` line at all (the `established`-vs-not distinction
        this replaced is gone; the filler thresholds in `detectLanguage()` already prevent a filler
        from *flipping* a language once one is set, so a single simpler always-on threshold now
        covers both the first turn and every turn after).
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
- [x] **Phase 10 — Azure VM deployment**, done 2026-09-03. Live at **https://104.211.224.38/**
      (self-signed cert — accept the warning once; http redirects to https). Deployment is versioned
      in `deploy/`: `telecom-assistant.service` (systemd, runs uvicorn on 127.0.0.1:8000 as
      `azureuser`, `Restart=always`, `MemoryMax=400M`), `nginx.conf` (80 → 301 → 443, TLS terminated,
      proxies to the app; audio never transits nginx — WebRTC is browser → Azure), and
      `setup_vm.sh` (idempotent: packages, venv + requirements as the non-root user, self-signed
      cert, nginx site, systemd unit rendered from the template; safe to re-run). **Redeploy is two
      lines on the VM**: `cd ~/telecom-assistant && git pull && sudo ./deploy/setup_vm.sh`.
      **Why HTTPS is mandatory**: browsers only grant `getUserMedia` (microphone) on a secure
      origin, so over plain http chat works but voice cannot open the mic. No domain exists for
      the VM, hence self-signed; `certbot --nginx` is the upgrade path once there's a domain.
      **Found on the first clean install**: `requirements.txt` pinned `truststore==0.9.2`, which
      pip can't resolve alongside `openai==3.7.0` — the local venv only worked because `openai` had
      been upgraded in place and pip bumped truststore with it. Now pinned `0.10.4`, verified with a
      resolver dry-run. Lesson: after any `pip install -U`, re-derive the pins from `pip freeze`.
      **Measured on the VM**: uvicorn RSS ~114 MB (matches the ~121 MB local measurement), 367 MB
      RAM still free, 2 GB swap already present; the 1 GB SKU is fine. Full 47-check
      `scripts/live_smoke.py` run against the VM: **46/47** — the one miss was bare "location?"
      landing on the generic clarification once, the same temperature-1 wobble documented above
      (re-run 6/6 against the VM immediately after). Everything that would indicate a deployment
      problem passed: outbound Azure OpenAI + telecom calls from the VM, TLS, the COMPLEX path,
      tool calls, security checks. Chat latency from the VM averages ~3.8s vs ~2.9s locally — it's
      farther from the model endpoint; nothing to fix.

## Open architecture discussions (decided in chat, not yet built — read before acting on either)

**1. Conversation memory + a ChatGPT-style "past chats" sidebar, per mobile number.**
Started as "does the LLM remember earlier turns" (answer: **no** — every LLM call site, chat router
included, sends only the system prompt + the *current* message, no history array; confirmed by
reading `llm.py`, `answer_synthesis.py`, `complex_flow.py` directly). The user then asked for
something bigger: a ChatGPT-style sidebar of past conversations, scoped per mobile number, using a
dropdown of demo numbers as a stand-in "login" (real auth is a different team's job, out of scope
here — treat a selected number as if it were an authenticated identity for this purpose). Points
actually settled, not just floated:
- **Key conversations by `session_id`, not `mobile_number`, for anything session-scoped** (e.g.
  short-term LLM context within one active chat) — keying by number risks two different
  browsers/devices silently sharing context if they pick the same demo number. But for the
  *sidebar* feature specifically, the user deliberately wants number-scoped history (that's the
  point of treating the dropdown as a login) — accepted with one known, acceptable limitation: two
  people demoing with the same test number will see each other's history, same as two people
  sharing one login would. Goes away once real auth lands.
  A **dropdown of a fixed set of demo numbers** (replacing the current free-text Account field) was
  agreed as the mechanism — not yet built.
- **Azure OpenAI's Responses API (`conversation`/`previous_response_id`) was considered and is the
  right tool for LLM-side memory specifically** (server-side history, no growing list to manage on
  the 1 GB VM, same ID concept as the "conversation id" the user saw in Azure AI Foundry Agent
  traces) — but it does NOT give a durable, queryable copy of transcripts you own; it's Azure's
  internal store, not a substitute for real persistence. Migrating chat's 3 LLM call sites from
  `chat.completions.create()` to `responses.create()` is a real API-surface change (different param
  names, different output shape) — not started, would need re-verifying the already-tuned
  intent-classification behavior afterward.
- **Cosmos DB was requested, pushed back on hard, then reconsidered once the user gave a real
  reason** (the pattern here will be reused at scale elsewhere, not just this POC — a legitimate
  basis to invest in the architecture now rather than defer it). Landed position: **yes, appropriate
  given that stated reason** — partition key `/mobileNumber` (matches the actual access pattern,
  keeps reads/writes in Cosmos's fast single-partition path), **one document per conversation**
  (metadata + embedded message array — avoids a separate messages container, avoids joins, minimal
  RU cost), free tier (1000 RU/s + 25GB, one account per subscription) very likely covers this POC's
  entire load. **Not started** — nothing in `requirements.txt`, no `azure-cosmos` code, no container
  created. What to ask the admin for (given to the user verbatim, worth reusing if this comes up
  again): an Azure Cosmos DB account, API "Azure Cosmos DB for NoSQL", same resource group as the
  VM, Free Tier if the subscription hasn't used its one free account elsewhere (else Serverless),
  database `telecom-assistant`, container `conversations`, partition key `/mobileNumber`, plus
  **Contributor** role on the resource for the user, and the connection string (goes in `.env`,
  never committed — same pattern as every other secret in this project).
- If this gets picked up: build the dropdown + `session_id`-scoped short-term memory first (small,
  self-contained, no new infra), Cosmos DB persistence as a distinct second step once the account
  exists.

**2. Azure OpenAI Realtime API (current) vs. Azure AI Voice Live API (a different Microsoft
product, not what this app uses).** The team apparently said Voice Live API "sounds more human."
Both are real, genuinely different products — Voice Live API is built on Azure AI Speech (separate
STT/TTS pipeline, historically, behind a unified session API, plus extras like built-in noise
suppression and possibly avatar/custom-voice support) vs. this app's native end-to-end
speech-to-speech Realtime API. Two distinct, real reasons "sounds more human" could be true point in
different directions: Azure's neural TTS voices have a strong reputation for natural *timbre*
independent of any LLM (points toward Voice Live API), while native speech-to-speech avoids losing
tone/emotion/hesitation through a text intermediate step, which is the traditional argument for more
natural *conversational* behavior (points toward Realtime API). Genuinely relevant to this specific
project, more than the general "sounds human" framing: **Azure Speech has invested heavily in
Indian-language quality** (Hindi/Telugu/Tamil/Kannada) specifically, which is exactly the hard part
this build has already spent real effort on (see Phase 8's language-switching work above) — that's
a more concrete reason to evaluate Voice Live API than a vague naturalness impression.
**Recommendation given, not yet acted on**: do NOT switch on secondhand impressions. Test both
live, side by side, in Azure AI Foundry's playgrounds, with real Hindi/Telugu/Tamil/Kannada phrases
relevant to this bot, before deciding. A real switch would be a genuine migration (different
session/auth setup) and risks having to re-solve some of the hard-won Realtime API quirks already
documented in Phase 8 above (transcription timing, session.update replace-not-merge, the
language-switch redesign) in a new form, since they may not carry over to a different architecture.

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

- Target VM: Azure 1 GB Ubuntu, public IP `104.211.224.38`, user `azureuser`. **Canonical URL is
  now `https://104-211-224-38.sslip.io/`** (real Let's Encrypt cert, see Update 4) — the raw IP
  still works but 301-redirects to that domain and shows a cert warning first if hit directly over
  https (see Update 4's nginx changes for why that one warning is unavoidable).
- **Outbound SSH is machine/network-dependent, not VM-side.** The machine used to build Phase 1–2
  sat behind a corporate network that blocked outbound port 22 entirely (confirmed against both the
  VM and `github.com:22`). Re-tested from a different machine on 2026-09-03: port 22 is open and a
  password-auth SSH login succeeds fine. So the "deploy via Azure Portal console" workaround below
  is a fallback for a blocked network, not a hard requirement — check `nc`/`Test-NetConnection` to
  `104.211.224.38:22` first; if it's open, a normal `git clone`/`git pull` over SSH from that machine
  works.
- **VM state as of 2026-09-03 (deployed)**: `~/telecom-assistant` is a git checkout of `main` with
  its own `.venv/` and the real `.env` (mode 600, never committed — copy it over by SFTP/scp when
  setting up a fresh VM). The previous venv-only folder was moved aside as
  `~/telecom-assistant.old-<timestamp>` and can be deleted. `~/voice-agent` is a separate,
  apparently unrelated folder (own `.venv`, a small `main.py`) — not part of this project, left
  untouched. Access facts: the GitHub repo is **public** (clone needs no token); `azureuser`'s
  `sudo` **requires the password** (no NOPASSWD), so scripted deploys pipe it to `sudo -S`.
  Service/logs: `systemctl status telecom-assistant`, `journalctl -u telecom-assistant -f`.
  **`.env` on the VM currently has a manual override not reflected anywhere in git**:
  `REALTIME_VAD_THRESHOLD=0.9` (see Update 7) — `setup_vm.sh` never touches `.env`, so this survives
  redeploys, but check the VM's actual `.env` before assuming voice behavior matches
  `.env.example`'s documented default.
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
