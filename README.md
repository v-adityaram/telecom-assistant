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
pytest
```

## Current status

See [`PROGRESS.md`](PROGRESS.md) for phase-by-phase status and open decisions blocking further work.
