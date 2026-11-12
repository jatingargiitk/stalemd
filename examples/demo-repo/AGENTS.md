# Agent guide

## Setup
```bash
make setup
npm install
cp .env.example .env
```

## Commands
- Run the dev server with `npm run dev`.
- Run unit tests with `npm test` before every commit.
- Lint with `pnpm lint`, then `make lint`.
- Python tests: `pytest tests/unit/test_server.py` and `python -m app.worker`.
- Seed data with `./scripts/seed.sh`; deploy with `./scripts/deploy.sh`.

## Layout
- API code lives in `src/api/routes.py`; the server is `src/app/server.py`.
- Built files go to `dist/` and are never committed.
- Read [the architecture notes](docs/architecture.md) and [the ADRs](docs/adr/README.md).
<!-- stalemd: ignore -->
- Old contributors may still have `legacy/run.py` around.
