# Telecom AI Assistant (POC)

Lightweight FastAPI backend for a telecom customer assistant (Chat + Realtime Voice).

- **Original plan**: [`docs/telecom_ai_assistant_implementation_plan.md`](docs/telecom_ai_assistant_implementation_plan.md) — the phase-by-phase spec this was built against.
- **How it actually works now**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — every LLM call site ("agent"), what each Python file does, the chat and voice request lifecycles, security model, and a diagram.
- **Chat request/response trace**: [`docs/chat-flow-diagram.svg`](docs/chat-flow-diagram.svg) — a sequence diagram tracing one message through the real code, step by step, both outcomes (answer / clarification).
- **Current progress and open decisions**: [`PROGRESS.md`](PROGRESS.md) — read this if you're picking this project up on a different machine/session than the one that last worked on it; its "Where things stand" section at the top is written as a fast-pickup summary, not just a log.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then fill in values
uvicorn app.main:app --reload
```

## Tests

```bash
pytest                                  # unit tests, fully mocked, no network
python scripts/live_smoke.py            # 47-check live matrix against a running server (needs .env)
SMOKE_BASE=https://<host> SMOKE_INSECURE=1 python scripts/live_smoke.py   # same, against the VM
```

## Deployment (Azure VM)

Everything needed lives in [`deploy/`](deploy/): a systemd unit, the nginx site, and an idempotent
`setup_vm.sh`. First time on a fresh VM:

```bash
git clone https://github.com/v-adityaram/telecom-assistant.git ~/telecom-assistant
# copy your .env into ~/telecom-assistant/.env (never committed), then:
cd ~/telecom-assistant && sudo ./deploy/setup_vm.sh
```

Every later release is the same two lines from the checkout:

```bash
git pull && sudo ./deploy/setup_vm.sh
```

nginx serves HTTPS under `https://<ip-with-dashes>.sslip.io/` (e.g. `104-211-224-38.sslip.io` for
`104.211.224.38`) with a real, browser-trusted Let's Encrypt certificate — no domain purchase needed,
sslip.io resolves that hostname straight to the embedded IP — and redirects 80 → 443. HTTPS is a
requirement, not polish: browsers only allow microphone access on a secure origin, so over plain http
the chat works but the voice button can't open the mic. `setup_vm.sh` obtains the certificate itself
on first run (via the HTTP-01 challenge, so port 80 needs to stay reachable from the internet) and
certbot's own timer renews it automatically afterward — nothing to do manually. Override the hostname
with `PUBLIC_DOMAIN=your.domain sudo -E ./deploy/setup_vm.sh` if you'd rather use a real domain you
own (point its A record at the VM's IP first).

Rotating a key: edit `.env` on the VM, then `sudo systemctl restart telecom-assistant`.

## Current status

See [`PROGRESS.md`](PROGRESS.md) for phase-by-phase status and open decisions blocking further work.
