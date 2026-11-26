# Data sources

How Ballpark gets property data, how to add a new source, and the compliance checklist every
source must pass first. The hard rules are in [GDD §12](GDD.md#12-compliance-rules-hard-requirements).

## Enabled sources

| Key | Source | Countries | Price type | Licence / terms |
|---|---|---|---|---|
| `uk_price_paid` | [HM Land Registry Price Paid Data](https://www.gov.uk/government/collections/price-paid-data) | GB (England & Wales) | `sale_record` | Open Government Licence v3.0 — attribution required |
| `example_html` | Fixture site in `backend/tests/fixtures/` (reference only, **disabled**) | PT, HR | `asking` | n/a |
| `demo` | Invented DEMO data loaded by `make seed` (not a plugin) | all 16 | both | n/a |

Required attribution text is stored in each plugin's `license_note` and copied to the `sources`
table on every run, so the About page (Phase 3) can list it.

## Compliance checklist (every new plugin must pass ALL of these)

Copy this list into the plugin's pull request and tick each item. If any box can't be ticked,
the source is not added.

- [ ] **Licence / terms checked.** The site's terms of use allow this use, or the data is
      published under an open licence. The licence and any required attribution text are recorded
      in the plugin's `license_note`.
- [ ] **robots.txt allows the paths** the plugin fetches, for the `BallparkBot` User-Agent
      (`discover()` and `fetch_and_parse()` URLs). PoliteClient enforces this at runtime, but
      check by hand first. If the paths are disallowed, the source can't be added.
- [ ] **Logged-out access only.** Every URL works in a private browser window with no account,
      cookie banner acceptance, API key the site didn't issue to us, or paywall.
- [ ] **No CAPTCHA, Cloudflare/bot challenge or similar** on the pages. If the site challenges
      us, the plugin stops (`SourceBlocked`) and we do not work around it.
- [ ] **All HTTP goes through `PoliteClient`** (`client.get` / `client.download`). No direct
      `httpx`/`requests` calls, no custom headers, no proxies, no headless browser (Playwright
      only for sites that render with JavaScript *and* allow crawling, and only after discussion).
- [ ] **Delay ≥ 2 s** per domain (`delay_seconds` in `sources.yaml`; default 5 s). Honour any
      longer `Crawl-delay`.
- [ ] **Facts only, no images or personal data.** The plugin returns `NormalizedListing` and
      nothing else. It does not download, link or keep photos, descriptions, agent/owner names,
      phone numbers, emails or street addresses (the dataclass has no fields for them).
- [ ] **Coordinates from the source or an open geocoder** (Nominatim / postcodes.io), never Google.
      `location_precision` is set honestly: `exact` (building), `street`, or `district`.
- [ ] **Link-back implemented**: `listing_url` points to the original listing or record when one
      exists (it's only shown on the reveal screen).
- [ ] **Attribution added** (`license_note`) if the licence requires it.
- [ ] **Sane volume**: `max_records_per_run` set to what's needed, not "everything".
- [ ] **Tests** against a saved fixture page (no live requests in tests), including a check that
      non-fact content on the fixture page doesn't end up in the database.
- [ ] **Removal works**: `source_ref` is stable, so blocklisting a record keeps it out for good.

## How to write a plugin

1. **Save fixtures.** Save one or two listing pages (and an index/search page if `discover()`
   needs one) into `backend/tests/fixtures/<source_key>/`. Replace any personal data in them with
   fake values.

2. **Write the plugin** in `backend/ingest/sources/<source_key>.py`. Start from
   `example_html.py`:

   ```python
   class MySource(SourcePlugin):
       key = "my_source"
       display_name = "My Source"
       homepage = "https://…"
       price_type = "asking"           # or "sale_record"
       country_codes = ["ES"]
       license_note = None              # or the attribution the licence requires

       def discover(self, client, settings):
           """Yield listing URLs or record IDs. Fetch index pages with client.get()."""

       def fetch_and_parse(self, client, ref):
           """Fetch one listing with client.get(ref) and return NormalizedListing, or None."""
   ```

   - Parse prices with `normalize.parse_price()` (handles `€ 340.000`, `R$ 1.050.000`,
     `3,800万円`, `$1.2M`…), areas with `parse_area()` (m², ft², sqm…) and types with
     `normalize_property_type()`.
   - Return `None` for anything you can't parse confidently. The pipeline counts skips.
   - Don't convert currencies. Return the source's own currency; the pipeline handles FX
     (and HRK → EUR).
   - If the source has no coordinates, use `self.ctx.geocoder.geocode_address(...)` and keep the
     address only in local variables.

3. **Register it** in `backend/ingest/sources/__init__.py` (`PLUGINS`).

4. **Configure it** in `backend/ingest/sources.yaml`, starting with `enabled: false`:

   ```yaml
   my_source:
     enabled: false
     delay_seconds: 5
     max_records_per_run: 50
     # anything else here is passed to discover() as `settings`
   ```

5. **Test it** (`backend/tests/test_ingest_<source_key>.py`) by serving the fixtures with the
   `fixture_site`/`server` pytest fixtures (a local HTTP server) and running `run_source`. See
   `test_ingest_example_html.py`.

6. **Tick the checklist**, enable the source, and do a small first run:

   ```bash
   backend/.venv/bin/python -m ingest run --source my_source --limit 10
   backend/.venv/bin/python -m ingest stats --by source,country
   ```

## What the pipeline does for every record

`discover` → (blocklist check) → `fetch_and_parse` → launch-country whitelist → HRK→EUR →
FX to USD at `price_date` → validation (price $5k–$100M, area 10–50,000 m², $50–$100k per m²,
…) → GHSL urban/suburban/rural classification → upsert on `(source, source_ref)` → flag possible
cross-source duplicates (≤ 15 m apart and ≤ 2% price difference). Each run writes a row to
`ingest_runs` with counts and rejection reasons. New records start with `sv_status='unchecked'`
and aren't playable until the Street View check (Phase 3) marks them `ok`.

## When a source blocks us

A 403, a 429 or a challenge page stops that source's run immediately. It's logged as `BLOCKED`
and the run is recorded with `status='blocked'`. Records saved before the block are kept. The
source isn't retried until its next scheduled run. If it keeps happening, disable the source;
don't work around it.

## Removal requests and takedowns

Removal requests and takedowns are handled by the `deactivate` / `remove` CLI commands and the
blocklist (Phase 3). Blocklisted `(source, source_ref)` pairs are skipped before they're fetched.
