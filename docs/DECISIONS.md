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

## Phase 2

19. **robots.txt status codes follow RFC 9309**: any 4xx (including 401/403) means "no rules,
    everything allowed"; 5xx or unreachable means "disallow everything" until it can be read.
    (Many static hosts, including S3 website endpoints, return 403 for a missing robots.txt.)
    A longer `Crawl-delay` in robots.txt overrides the source's `delay_seconds`.
20. **PoliteClient is synchronous with one lock per domain**, so "max 1 concurrent request per
    domain" holds even if a plugin uses threads. Its on-disk cache is a small SQLite file
    (`data/cache/http_cache.sqlite`) rather than `hishel`, to keep dependencies minimal. Only
    HTTP 200 responses are cached. Cookies are refused by a cookie policy, so nothing is ever
    stored or sent.
21. **Bulk downloads** (Land Registry CSVs, the GHSL zip) go through `PoliteClient.download()`:
    robots.txt is checked, they're streamed to disk, and a file younger than 7 days is reused.
22. **APIs** (Frankfurter, Nominatim, postcodes.io) are called with plain `httpx` and the same
    honest User-Agent, not through PoliteClient. They're APIs with their own usage policies, not
    crawled pages. A 403/429 from a geocoder still stops the run (`SourceBlocked`).
23. **Geocoding precision from Nominatim `place_rank`**: ≥ 28 = `exact` (building / house
    number), 26–27 = `street`, coarser = no match → postcode centroid from postcodes.io
    (`district`, not playable). The geocode cache stores SHA-256 hashes of queries plus
    coordinates only, so addresses never touch disk. Public Nominatim is throttled to just under
    1 request/second. A self-hosted `NOMINATIM_URL` isn't throttled.
24. **UK Price Paid**: uses the monthly update file by default (configurable `urls:`; or
    `local_path`). Keeps `ppd_category = A` and `record_status` A or C, property types D/S/T/F.
    D and S map to `house`, T to `townhouse`, F to `apartment`. City is the CSV's town (title-cased);
    region is the county. `listing_url` links to the record on landregistry.data.gov.uk (only
    shown on reveal). Sampling is round-robin across counties. The plugin's geocoder lookups count
    toward the run, so a 2,000-record run takes ~35 min on public Nominatim.
25. **FX**: rates are fetched a calendar year at a time on demand (one request per year, all
    launch currencies), then looked up for `price_date` or up to 10 days earlier. `fx-update`
    fetches the last 30 days and mirrors `data/fx_manual.csv` (TWD) into `fx_rates` as
    first-of-month rows, so Hard mode's latest-rate lookup works for TWD too. Which currencies
    are ECB-covered is a field on each country in `countries.py` (`in_ecb_fx`).
    `data/fx_manual.csv` ships with only a header row. The owner fills in TWD monthly averages
    from an official source. Until then, TWD records are skipped and logged.
26. **HRK**: any price a plugin returns in HRK is converted to EUR at 7.53450 and stored as EUR,
    whatever its date (the pipeline does this, not each plugin).
27. **Cross-source duplicates** are flagged, not merged: counted on the run row, logged, and up to
    50 id pairs stored in `ingest_runs.details`. Both records stay active for now.
28. **Moving a record resets its Street View status**: if an update changes its coordinates,
    `sv_status` goes back to `unchecked` and `pano_id` is cleared.
29. **`ingest_runs`** (GDD §10.3) was added in migration 0002 with counts, status
    (`ok`/`blocked`/`error`), rejection reasons and a message.
30. **CLI scope**: Phase 2 ships `run`, `fx-update`, `stats`, `reclassify-settings` and
    `setting-data download`. `streetview-check`, `deactivate`, `removals` and `remove` arrive with
    Phase 3 (Street View + removal path), as the phase plan lists them there.
31. **`stats --by`** accepts any comma-separated mix of `country, source, sv_status, setting,
    precision, type, price_type` (the Phase 5 `--by country,setting` example works already).
32. **rasterio + pyproj are regular dependencies** (wheels bundle GDAL). The classifier opens the
    raster once per run and uses `DatasetReader.sample`, which handles over 5,000 points/s in
    tests.
