# Ballpark

> Guess the price, get in the ballpark.

A browser game: you see a real property listing somewhere in the world (its listing photos plus a
few facts) and guess what it's listed or sold for. Closer guesses score more (log-scaled, max
5,000 per round).

The design and technical spec is [`docs/GDD.md`](docs/GDD.md) (v2, with the owner's amendments in
§0.2). Choices made where the spec was ambiguous are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Playable skeleton: seed data with placeholder photos, scoring, selection, Classic, Normal + Hard | done |
| 2 | Scraper framework: PoliteClient, FX, validation, photo URL checks, refresh job, GHSL classifier, example plugin | done |
| 3 | Daily, leaderboards, Urban/Rural toggles, mini map, photo reports, removals, CSP from image hosts | done |
| 4 | Regional, Higher/Lower, polish, backups, cron, deployment guide | – |
| 5 | Real listing sites, one at a time, chosen by the owner | waiting for the owner |

**No API keys are needed.** The game plays on 51 invented DEMO homes with original placeholder
illustrations until the owner adds a real listing site (see "Adding listing sites" below).

## Quick start (local development)

Requirements: Python ≥ 3.12, Node 22 LTS, `make`.

```bash
make install   # creates backend/.venv, installs npm deps, copies .env.example -> .env
make seed      # migrates the SQLite DB and loads the 51 DEMO homes
make dev       # API on http://localhost:8000, game on http://localhost:5173
```

`make dev` stops any leftover dev servers first (e.g. after a Codespace reload); `make stop` does
just that.

With the demo seed only **World** is selectable: each region/country needs
`MIN_POOL_PER_OPTION` (default 50) eligible homes. Set `MIN_POOL_PER_OPTION=5` in `.env` to try
regions in development.

### Make targets

| Target | What it does |
|---|---|
| `make dev` / `make stop` | API with reload (:8000) + Vite with `/api` proxy (:5173) / stop them |
| `make test` | Backend pytest + frontend type-check and Vitest |
| `make e2e` | Playwright smoke test (starts its own servers and a throwaway DB) |
| `make lint` | Ruff + TypeScript |
| `make migrate` / `make seed` | `alembic upgrade head` / load demo data (idempotent) |
| `make ingest ARGS="…"` | the ingest CLI (below) |
| `make csp` | write `deploy/csp.env` (CSP `img-src` from enabled sources' `image_hosts`) |
| `make build` | production frontend build into `frontend/dist` |
| `make up` / `down` / `logs` | docker compose stack (regenerates the CSP first) |

## Adding listing sites (Phase 5)

All property data comes from listing sites **you** choose, one at a time. For each site:

1. Read its terms and robots.txt, and go through the checklist in
   [`docs/SOURCES.md`](docs/SOURCES.md).
2. Tell Claude Code which site and confirm the checklist; it writes the plugin from the
   `example_html` template with saved fixture pages and tests.
3. Enable it in `backend/ingest/sources.yaml`, do a small run, then the regular jobs:

```bash
make ingest ARGS="run --source <key> --limit 10"
make ingest ARGS="stats --by source,images"
make ingest ARGS="images-check"          # verify photo URLs (also runs after each import)
make ingest ARGS="refresh"               # daily: delisted homes leave the pool
make ingest ARGS="fx-update"             # daily: exchange rates
make ingest ARGS="setting-data download" # once: GHSL raster for urban/rural (~18 MB)
make csp                                  # after enabling a source with new image hosts
```

Players can report a photo (e.g. "the price is visible") and anyone can request removal on the
About page: `make ingest ARGS="reports"` and `make ingest ARGS="removals"` list them;
`remove --property-id <id>` takes a home and its photo URLs out for good.

## Layout

```
backend/   FastAPI app (app/), ingestion framework (ingest/), Alembic migrations, pytest
frontend/  Vite + React + TypeScript; public/demo-photos/ has the seed's placeholder images
deploy/    docker-compose.yml, Caddyfile (CSP from deploy/csp.env)
docs/      GDD, decisions log, SOURCES.md (checklist + plugin guide)
data/      SQLite DB, caches, GHSL raster, fx_manual.csv: never committed
```

## Self-hosting (preview)

```bash
cp .env.example .env    # set DOMAIN, PUBLIC_BASE_URL, CONTACT_EMAIL, SCRAPER_USER_AGENT, DAILY_SALT…
make up                 # builds API + frontend, writes the CSP, Caddy gets HTTPS for $DOMAIN
docker compose -f deploy/docker-compose.yml --env-file .env exec api python -m app.seed  # optional demo data
```

A full VPS / home-server guide, backups and the cron container come in Phase 4.

## Photos, data & compliance

Photos are shown **directly from the listing site** (hotlinked), exactly as published, credited
("Photos: {site}") and always linked back. They are never downloaded, cached, proxied, edited or
cropped. We store facts and photo URLs only, never descriptions or anyone's contact details, use
only coordinates the listing provides (no geocoding, nothing from Google), scrape politely
(robots.txt, delays, honest User-Agent, stop when blocked) and remove anything on request within
72 hours. Non-commercial at launch. See GDD §12.

Credits: urban/rural classification from GHSL GHS-SMOD (European Commission JRC, CC BY 4.0);
exchange rates from the ECB via Frankfurter; maps © OpenStreetMap contributors.
