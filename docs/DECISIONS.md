# Decisions log

Choices made where the GDD was ambiguous (GDD §0 rule 8). Newest at the bottom of each phase.

## Phase 1

1. **Repo root = project root.** The GDD shows a `ballpark/` top folder; this repository *is* that
   folder, so `backend/`, `frontend/`, `deploy/`, `docs/` live at the repo root.
2. **Run everything from the repo root.** `.env`, `data/` (SQLite DB, future GHSL raster and
   `fx_manual.csv`) are resolved relative to the repo root, matching the relative paths in GDD §9.5.
   The Makefile, Alembic and Uvicorn are all invoked from there.
3. **FX rate direction.** `fx_rate_to_usd` = USD per 1 unit of local currency, so
   `price_usd = price_local × fx_rate_to_usd`. GDD §6.5's "USD_MIN × rate" is read as "converted to
   local", i.e. `USD_MIN / fx_rate_to_usd` with this storage convention.
4. **Hard-mode slider rounding.** Bounds are rounded *outward* to 1/2/5 × 10ⁿ (min down, max up)
   so the local range always covers the full $5k–$50M range. E.g. JPY at 150 → ¥500,000 –
   ¥10,000,000,000 (the GDD's ¥750,000 – ¥7,500,000,000 example isn't itself 1/2/5-rounded).
   The rate used is the latest row in `fx_rates` for the currency (cached per day in memory),
   falling back to the property's stored rate.
5. **`fx_hint` is `null` for USD properties** ("1 USD ≈ 1 USD" is noise). Present for all others.
6. **Country weighting fallback.** World games weight countries equally among those with
   ≥ `MIN_POOL_PER_OPTION` eligible properties. If fewer than 3 countries qualify (not enough to
   fill 5 rounds under the ≤ 2-per-country rule) every country with eligible properties is used.
   This keeps the demo seed (3–4 per country) playable.
7. **Selection relaxation order.** If the pool can't satisfy every balancing rule, rules are
   dropped in this order: urban/suburban mix → price-quintile spread → unique city → ≤ 2 per
   country. Each level gets 200 randomized attempts. Quintiles are computed over the pool being
   played (World, region, or country) rather than globally.
8. **World is always selectable** when it has ≥ 5 eligible properties (enough for one game).
   Regions and countries need ≥ `MIN_POOL_PER_OPTION` (default 50) *and* ≥ 5.
9. **Round-order errors.** Re-guessing a round or skipping ahead returns **409**; an unknown game
   or round number returns **404**; validation problems (bad amount, wrong currency) return **422**.
   Guess amounts must be JSON numbers (strings are rejected) in (0, 10¹³).
10. **The API already accepts `mode: urban | suburban`** (it's just a setting filter), but the Home
    screen only shows Classic until Phase 3 per the phase plan. `mode: daily` is rejected by
    `POST /games`; Daily gets its own endpoint in Phase 3.
11. **Street View in Phase 1.** `streetview_url` is always `null` and the client shows a placeholder.
    The pure helpers (heading, URL signing — verified against Google's documented example) are
    already in `core/streetview_urls.py`. DEMO properties are marked `sv_status='ok'` without a
    `pano_id` so they're playable without a Google key.
12. **Seed data**: 51 fictional DEMO properties (every country has ≥ 3; 19 urban, 21 suburban,
    11 rural), deterministic UUIDs so `make seed` is idempotent; price dates are relative to today
    so they never age out of `MAX_PRICE_AGE_YEARS`. Coordinates are approximate city/neighborhood
    points, not real addresses. "Asking" demo records get an `https://example.com/demo/…` link so
    the "See original listing" path is exercised.
13. **Meta endpoint** lives in `api/meta.py` (not listed in GDD §9.2 but needed by §9.4). It also
    returns `contact_email` for the footer's "Request removal" mailto link until the removal form
    ships in Phase 3.
14. **Accent color / vibe** (open question 2) defaults to a burnt orange (`#c2410c`, AA contrast with
    white text) on an off-white background, with a matching dark palette via
    `prefers-color-scheme`. Easy to change in `frontend/src/styles/global.css`.
15. **Rate limiting** is in-memory per IP and per worker (simple; fine for one small server).
    Configure with `RATE_LIMIT_GAMES_PER_HOUR` / `RATE_LIMIT_GUESSES_PER_HOUR`; 0 disables.
16. **Docker "web" service** is a one-shot container that builds the frontend and copies it into a
    volume served by Caddy. The `cron` container and `backup.sh` are Phase 4 items.
17. **Input shorthand**: `k`/`m`/`b` suffixes, case-insensitive; "1,5m" (decimal comma) works.
    Plain numbers treat every `.`/`,` as a grouping separator (prices are whole numbers).
18. **`make test`** runs backend (pytest) and frontend (tsc + Vitest) tests. The Playwright smoke
    test is `make e2e` (it starts its own API + Vite servers on spare ports with a throwaway DB).
