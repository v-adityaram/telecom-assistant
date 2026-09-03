# Telecom AI Assistant (POC)

Lightweight FastAPI backend for a telecom customer assistant (Chat + Realtime Voice).

- **Architecture and phase-by-phase plan**: [`docs/telecom_ai_assistant_implementation_plan.md`](docs/telecom_ai_assistant_implementation_plan.md) — read this first.
- **Current progress and open decisions**: [`PROGRESS.md`](PROGRESS.md) — read this second, especially
  if you're picking this project up on a different machine/session than the one that last worked on it.

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

nginx serves HTTPS with a self-signed certificate and redirects 80 → 443. That's a requirement, not
polish: browsers only allow microphone access on a secure origin, so over plain http the chat works
but the voice button can't open the mic. Accept the certificate warning once. If you later point a
domain at the VM, `certbot --nginx` replaces the self-signed cert and nothing else changes.

Rotating a key: edit `.env` on the VM, then `sudo systemctl restart telecom-assistant`.

## Current status

See [`PROGRESS.md`](PROGRESS.md) for phase-by-phase status and open decisions blocking further work.
