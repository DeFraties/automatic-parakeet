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

## Phase 3

33. **Owner answers to GDD §15** (2026-11-27): (1) keep "Ballpark" / placeholder domain;
    (2) keep the burnt-orange accent; (3) the Daily Challenge mixes recorded sale and asking
    prices; (4) no timer, no "extra hard" mode; (5) rural properties are played.
34. **Neighbourhood toggles replace the Urban / Suburban mode cards** (owner decision). Every
    Classic game carries a setting selection, any non-empty subset of urban / suburban / rural,
    **default urban + rural**. The Home screen shows three toggles (at least one stays on); the
    choice is remembered in localStorage. `games.setting_filter` and
    `leaderboard_entries.setting_filter` store it in canonical form (alphabetical,
    comma-joined: `rural,urban`). Leaderboards are kept separate per combination, so "Urban
    only" or "Suburban only" boards still exist. `POST /api/games` takes `settings: [...]`
    instead of `mode: urban|suburban`.
35. **Setting mix in selection**: with two settings selected, at least 2 rounds of each; with
    three, at least 1 of each (when the pool allows; relaxed otherwise, like the other rules).
36. **Daily Challenge** is always World with the default settings (urban + rural), mixes price
    types, and is generated from `sha256(date + DAILY_SALT)`. Lazy generation uses the
    `daily_challenges.date` primary key as the lock (a racing second insert fails and re-reads).
    `python -m app.jobs daily` creates it ahead of time (cron container in Phase 4). One attempt
    per device per UTC day, enforced by the `(date, device_id)` unique constraint. An unfinished
    Daily can be **resumed** (`GET /api/games/{id}`, same device only) so a page reload doesn't
    burn the day's attempt. The daily number is clamped to ≥ 1 before `LAUNCH_DATE`.
37. **Quota**: `sv_usage.urls_issued` counts every signed URL, and `daily_reserved_used` counts
    those for Daily games. Non-daily games may start while their usage + 5 ≤
    `GOOGLE_DAILY_QUOTA - DAILY_RESERVED`; the Daily may start while total usage + 5 ≤
    `GOOGLE_DAILY_QUOTA`. Blocked starts return 503 `quota_exceeded` with the spec's message.
    Without a Google key/secret, no URLs are issued and the quota never blocks anything.
38. **Street View at round time**: the panorama location comes from the free metadata endpoint
    (cached in memory 10 min, never stored) and gives the camera heading. If the lookup fails, the
    URL is issued without a heading (Google picks a default view). URLs are only issued when a
    round is actually shown (round 1 at start, round n+1 in the guess response, or on resume).
39. **Image-error telemetry doesn't delete anything.** A report sends the property back to
    `sv_status='unchecked'`; the next `ingest streetview-check` re-verifies it and marks it
    `none` only if Google has no imagery. Only rounds the reporting device has been shown can
    be reported.
40. **`streetview-check`** skips `district`-precision records (never playable) to save calls.
    A Google error (REQUEST_DENIED, OVER_QUERY_LIMIT…) stops the run without marking anything.
41. **Leaderboard submissions** need the same `X-Device-Id` that played the game, a completed
    game and a nickname that passes the filter (3–16 chars of letters/digits/space/`.`/`-`/`_`,
    plus a small multilingual blocklist after leetspeak normalisation). The score is always the
    server's. One entry per game. "Today" = since 00:00 UTC; "7 days" is rolling.
42. **Removal path**: `POST /api/removals` (email + listing URL/property ID + message),
    `ingest removals`, `ingest remove --property-id … [--request N]` (deactivates and
    blocklists it, and marks the request done), `ingest deactivate --source KEY`. Write
    endpoints (removals, leaderboard, telemetry) share a per-IP limit
    (`RATE_LIMIT_WRITES_PER_HOUR`, default 30).
43. **Simple hash routing** (`#/leaderboards`, `#/about`) instead of a router library.
44. **Mini map**: Leaflet with OSM tiles (`TILE_URL` / `TILE_ATTRIBUTION`, served via
    `/api/meta`), a plain circle marker (no image assets), zoom 10, at the server-rounded
    (~1 km) coordinates. On phones it sits below the guess box so the input stays near the image.
45. **Migration 0003 doesn't rebuild `games` on SQLite.** SQLite ignores VARCHAR lengths, and
    rebuilding a table that `game_rounds` references fails once games exist (foreign keys are
    on). The column is only widened on other databases.

## Images (owner change, 2026-11-27)

46. **Owner decision: listing photos allowed (GDD §12 rule 1 amended, option "B").** A plugin
    may return the main photo's URL on the source (`image_url`). It is hotlinked: the player's
    browser loads it from the source with the default referrer policy (we don't strip the
    referrer to get around hotlink protection; a blocked image just falls back). Image bytes are
    never downloaded or re-hosted. Credited as "Photo: {source}" with the link back on reveal.
    `photos: false` per source and `ingest strip-photos --source KEY` give an immediate
    photo-only takedown. The owner accepts the copyright risk. A listing photo's URL can identify
    the listing (and so its price) for a determined player. That's accepted for now; proxying to
    hide it would mean copying the image, which rule 1 still forbids.
47. **Mapillary added; Google Street View optional.** Image order per round: listing photo →
    Street View (only with a key) → Mapillary → illustrated card. `mapillary-check` picks a
    non-panoramic image 3–60 m away whose camera points within 75° of the house (score =
    metres + 0.3 × degrees off-axis), stores only its ID, and stops without marking anything on
    an API error. Thumbnail URLs expire, so they're resolved at round time and cached in memory
    for an hour. The Mapillary API shape is from its documentation and is covered by tests with
    a mocked API, but hasn't been run against the live service (no token in this environment).
48. **Homes without a photo are playable** (`ALLOW_IMAGELESS_ROUNDS=true`, default) with an
    illustrated card themed by setting and property type. Selection prefers homes with a photo
    and uses imageless ones as filler. With `false`, a photo is required. This replaces the
    v1 rule "playable only if `sv_status='ok'`".
49. **Image-error reports carry the source** and forget only that link: a listing URL is cleared
    (the next ingest run restores it if it still works), and Google/Mapillary go back to
    `unchecked`. The home itself is never deactivated by a report.
50. **CSP `img-src` is now `'self' data: https:`**, because listing photos can come from any
    HTTPS host.
51. **Data snapshots** (`ingest snapshot export|load`, `make load-uk`): one machine does the
    slow import, others load the result. The owner chose to commit the UK snapshot to the
    **public** repository (2026-11-27), knowing it publishes exact coordinates and sale prices
    of real homes. Only building/street-precision records are included (`--playable-only`), and
    no addresses or postcodes (the schema has none). Loading never re-activates a removed home
    and skips blocklisted ones. Attribution is in `data/snapshots/README.md`. Because the
    coordinates derive from OpenStreetMap/Nominatim, the file is shared under ODbL terms.
52. **Only homes with a photo are played** (owner decision, 2026-11-27):
    `ALLOW_IMAGELESS_ROUNDS` now defaults to `false`. Exception: if no photo source is
    configured at all (no `MAPILLARY_TOKEN`, no Google key), imageless homes stay playable so
    local development on demo data still works. Listing photos count as photos.
53. **Background photo check.** With photos required, unchecked homes would never be dealt and so
    never checked on the fly, so the API runs a background thread (when `MAPILLARY_TOKEN` is
    set) that checks unchecked building/street-precision homes at
    `BACKGROUND_PHOTO_CHECK_PER_SECOND` (default 5). It pauses 5 minutes on API errors and looks
    for new homes every minute when idle. A file lock in `INGEST_CACHE_DIR` keeps it to one
    thread across Uvicorn workers. `/api/meta` reports `photo_check_pending`, and the Home screen
    shows progress. `ingest mapillary-check` remains for bulk runs outside the server.
54. **Street View heading rounding bug fixed**: 359.95°+ was formatted as "360.0". Headings
    are now wrapped after rounding.
