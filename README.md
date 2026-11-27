# Ballpark

> Guess the price, get in the ballpark.

A browser game: you see a real property somewhere in the world plus a few clues, and guess what
it sold or is listed for. Closer guesses score more (log-scaled, max 5,000 per round).

The full design and technical spec is in [`docs/GDD.md`](docs/GDD.md); choices made where the
spec was ambiguous are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

**Phase 3 — images + Daily** ✅ Listing photos (hotlinked), Mapillary and optional Google Street
View, illustrated fallback cards, OpenStreetMap mini map, Daily Challenge, leaderboards,
urban / suburban / rural toggles, About page with a removal form, and removal CLI commands.

| Phase | Scope | Status |
|---|---|---|
| 1 | Skeleton, seed data, scoring, selection, Classic, Normal + Hard | done |
| 2 | Ingest framework, FX, GHSL classifier, UK Price Paid | done |
| 3 | Street View, Daily, leaderboards, neighbourhood toggles, About + removal | done |
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
| `make dev` | API with reload (:8000) + Vite with `/api` proxy (:5173); stops leftover copies first |
| `make stop` | Stop dev servers left running (e.g. after a Codespace reload) |
| `make test` | Backend pytest + frontend type-check and Vitest |
| `make e2e` | Playwright smoke test (starts its own servers and a throwaway DB) |
| `make lint` | Ruff + TypeScript |
| `make migrate` | `alembic upgrade head` |
| `make seed` | Migrate + load demo data (idempotent) |
| `make build` | Production frontend build into `frontend/dist` |
| `make up` / `down` / `logs` | docker compose stack (API + Caddy + static frontend) |

## Going live with real data

**Quickest start:** `make load-uk` loads 1,283 real UK sales from
[`data/snapshots/`](data/snapshots/README.md) in seconds, with no import needed.

Imported homes are playable straight away. Homes without a photo show an illustrated card.
Photos come from, in order: the listing source's own photo (hotlinked, credited) → Google Street
View (optional) → Mapillary → the illustrated card.

1. **Free photos via Mapillary** (recommended): create a free account and an app at
   https://www.mapillary.com/dashboard/developers, put its client token in `.env` as
   `MAPILLARY_TOKEN`, then `make ingest ARGS="mapillary-check --limit 2000"`.
2. **Optional: Google Street View** (paid beyond the free tier): in Google Cloud Console enable
   the **Street View Static API**, create a key restricted to it plus a **URL signing secret**,
   set `GOOGLE_MAPS_API_KEY` / `GOOGLE_URL_SIGNING_SECRET`, then
   `make ingest ARGS="streetview-check --limit 2000"`. `GOOGLE_DAILY_QUOTA` caps cost.
3. Optionally remove the demo data from play: `make ingest ARGS="deactivate --source demo"`.
4. Check coverage: `make ingest ARGS="stats --by source,setting"`.

The Daily Challenge for a day is created on its first request (or ahead of time with
`backend/.venv/bin/python -m app.jobs daily`). Removal requests from the About page are listed
with `make ingest ARGS="removals"` and handled with `make ingest ARGS="remove --property-id <id>"`.

## Data ingestion

All commands run from the repo root (`make ingest ARGS="…"` is the same as
`backend/.venv/bin/python -m ingest …`).

```bash
# One-time setup
#   1. In .env, set SCRAPER_USER_AGENT to something that identifies you (Nominatim's policy).
#   2. Download the GHSL settlement raster (~18 MB) used for urban/suburban/rural:
make ingest ARGS="setting-data download"
#   3. Monthly TWD rates (not published by the ECB) go in data/fx_manual.csv.

make ingest ARGS="fx-update"                       # refresh FX rates
make ingest ARGS="run --source uk_price_paid"      # ~2,000 records, ~35 min on public Nominatim
make ingest ARGS="run --all"                       # every enabled source in sources.yaml
make ingest ARGS="stats"                           # counts by source / country / sv_status
make ingest ARGS="stats --by country,setting"
make ingest ARGS="reclassify-settings"             # after a new GHSL file or rule change
```

Sources are configured in `backend/ingest/sources.yaml`. **Before adding a new source, read
[`docs/SOURCES.md`](docs/SOURCES.md)**: it has the compliance checklist and a plugin guide.

## Layout

```
backend/   FastAPI app (app/), ingestion (ingest/), Alembic migrations, pytest suite
frontend/  Vite + React + TypeScript game client, Vitest + Playwright tests
deploy/    docker-compose.yml, Caddyfile
docs/      GDD, decisions log
data/      SQLite DB, GHSL raster, caches (not committed); fx_manual.csv
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

Sources so far: invented **DEMO** data and HM Land Registry Price Paid Data (Contains HM Land
Registry data © Crown copyright and database right. Licensed under the Open Government Licence
v3.0). Urban/suburban/rural comes from GHSL GHS-SMOD (European Commission JRC, CC BY 4.0).
Everything follows the hard compliance rules in GDD §12: facts only, no stored photos or Google
content (except `pano_id`), polite robots.txt-respecting fetching that stops when blocked,
link-back and a removal path.
