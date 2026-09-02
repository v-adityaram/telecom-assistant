# Telecom AI Assistant (POC)

Lightweight FastAPI backend for a telecom customer assistant (Chat + Realtime Voice).
See `telecom_ai_assistant_implementation_plan.md` in the repo root for the full architecture and phase plan.

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

- Phase 1: FastAPI foundation — done (`/health`, config, logging, global exception handling, CORS).
- Remaining phases: see implementation plan.
