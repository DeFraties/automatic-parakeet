# Ballpark

> Guess the price, get in the ballpark.

A browser game: you see a real property somewhere in the world plus a few clues, and guess what
it sold or is listed for. Closer guesses score more (log-scaled, max 5,000 per round).

The full design and technical spec is in [`docs/GDD.md`](docs/GDD.md); choices made where the
spec was ambiguous are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

**Phase 1 — playable skeleton** ✅ Classic mode, Normal (USD) and Hard (local currency), on demo
data. No scraping, no Google key needed.

| Phase | Scope | Status |
|---|---|---|
| 1 | Skeleton, seed data, scoring, selection, Classic, Normal + Hard | done |
| 2 | Ingest framework, FX, GHSL classifier, UK Price Paid | – |
| 3 | Street View, Daily, leaderboards, Urban/Suburban modes, About + removal | – |
| 4 | Regional, Higher/Lower, polish, backups, cron, deployment guide | – |

## Quick start (local development)

Requirements: Python ≥ 3.12, Node ≥ 20, `make`.

```bash
make install   # creates backend/.venv, installs npm deps, copies .env.example -> .env
make seed      # migrates the SQLite DB and loads 51 fictional DEMO properties
make dev       # API on http://localhost:8000, game on http://localhost:5173
```

Open http://localhost:5173 and play. Without a Google key the round shows a placeholder image
instead of Street View.

With the demo seed, only **World** is selectable: each region/country needs
`MIN_POOL_PER_OPTION` (default 50) eligible properties. Set `MIN_POOL_PER_OPTION=5` in `.env` to
try region presets in development.

### Make targets

| Target | What it does |
|---|---|
| `make dev` | API with reload (:8000) + Vite with `/api` proxy (:5173) |
| `make test` | Backend pytest + frontend type-check and Vitest |
| `make e2e` | Playwright smoke test (starts its own servers and a throwaway DB) |
| `make lint` | Ruff + TypeScript |
| `make migrate` | `alembic upgrade head` |
| `make seed` | Migrate + load demo data (idempotent) |
| `make build` | Production frontend build into `frontend/dist` |
| `make up` / `down` / `logs` | docker compose stack (API + Caddy + static frontend) |

## Layout

```
backend/   FastAPI app (app/), Alembic migrations, pytest suite
frontend/  Vite + React + TypeScript game client, Vitest + Playwright tests
deploy/    docker-compose.yml, Caddyfile
docs/      GDD, decisions log
data/      SQLite DB and (later) GHSL raster / manual FX CSV — not committed
```

Key backend modules:

- `app/core/countries.py` — the 16 launch countries; the only country list in the codebase
- `app/core/scoring.py` — `score = round(5000 × max(0, 1 − |ln(guess/actual)| / ln 3))`, labels,
  Hard-mode slider bounds
- `app/core/selection.py` — eligibility rules and pool balancing (no repeated city, ≤ 2 per
  country, price-band spread, urban/suburban mix, equal country weighting)
- `app/api/games.py` — `POST /api/games`, `POST /api/games/{id}/rounds/{n}/guess`. Prices never
  leave the server before a guess; listing URLs only appear in reveals.

## Self-hosting (preview)

```bash
cp .env.example .env    # set DOMAIN, PUBLIC_BASE_URL, CONTACT_EMAIL, DAILY_SALT…
make up                 # builds API + frontend, Caddy gets HTTPS for $DOMAIN automatically
docker compose -f deploy/docker-compose.yml --env-file .env exec api python -m app.seed  # optional demo data
```

A full VPS / home-server guide, backups and the cron container come in Phase 4.

## Data & compliance

Phase 1 ships only invented **DEMO** data. Real sources arrive in Phase 2 under the hard
compliance rules in GDD §12: facts only, no stored photos or Google content (except `pano_id`),
polite robots.txt-respecting scraping that stops when blocked, link-back and a removal path.
