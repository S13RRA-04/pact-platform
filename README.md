# PACT Learning & Case Simulation Platform

Local, synthetic-data-only development prototype for the PACT cyber investigation training program. It is not authorized for operational use.

## Start locally

Prerequisites: Docker Desktop, Python 3.12+, and Node.js 20+.

1. Copy `.env.example` to `.env` and set a development-only `PACT_SESSION_SECRET`.
2. Start PostgreSQL: `docker compose up -d db`.
3. Backend setup: `cd backend`, create/activate a virtual environment, then run `pip install -e ".[dev]"`.
4. Apply the schema: `alembic upgrade head`.
5. Seed synthetic data: `python -m app.seed`.
6. Start the API: `uvicorn app.main:app --reload`.
7. In another terminal: `cd frontend && npm install && npm run dev`.
8. Open `http://localhost:3000`.

The Next.js development server proxies `/api/*` to `http://127.0.0.1:8000`. Override with the server-only `PACT_API_ORIGIN` environment variable.

## Verification

From `backend`: `ruff check app alembic tests && ruff format --check app alembic tests && pytest`.

From `frontend`: `npm run typecheck && npm run build`.
