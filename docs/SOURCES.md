# Listing sources

All property data (price, facts, location and photos) comes from **listing sites the owner
chooses**, one at a time (GDD Phase 5). This guide has the compliance checklist every source must
pass before it's enabled, and a walkthrough of the example plugin to copy.

The hard rules are in [GDD §12](GDD.md#12-compliance-rules-hard-requirements). In short:
photos are **hotlinked only**, shown exactly as published, always credited and linked back; no
personal data; polite scraping with **no circumvention of anything**, including hotlink
protection; no Google and no geocoding.

## Enabled sources

| Key | Site | Countries | Image hosts | Status |
|---|---|---|---|---|
| `example_html` | Fictional fixture pages in `backend/tests/fixtures/` | PT, HR | `images.example.test` | reference only, **disabled** |
| `demo` | 51 invented homes from `make seed` (not a plugin) | all 16 | our own site (`/demo-photos/`) | development |

## Checklist — every item before `enabled: true`

Copy this into the plugin's pull request. If any box can't be ticked, the source isn't added.

- [ ] **The owner has read the site's terms of use and robots.txt**, and robots.txt allows the
      listing pages, the search/discovery pages **and the image paths** on its image hosts for
      the `BallparkBot` User-Agent.
- [ ] **Works logged out**, with no challenge pages (Cloudflare, CAPTCHA). If the site
      challenges us, the plugin stops (`SourceBlocked`) and we don't work around it.
- [ ] **Delay ≥ 5 s for pages** (`delay_seconds`), ≥ 1 s for image checks
      (`image_delay_seconds`). A longer robots.txt `Crawl-delay` wins.
- [ ] **Only schema fields are extracted**: facts, photo URLs and the listing's *own*
      coordinates (`NormalizedListing` / `NormalizedImage`). No descriptions, no agent, owner or
      photographer names, phone numbers or emails, no street addresses, no image files.
- [ ] **`image_hosts` set correctly** in `sources.yaml` (and the plugin's default). Photo URLs on
      any other host are rejected at ingestion and blocked by the CSP. HTTPS only.
- [ ] **Photos are URLs the site publishes**: in the listing's order, the largest size the site
      already serves that is ≤ ~1600 px wide. Never request sizes the site doesn't publish,
      never download, resize, crop or re-host, never strip watermarks.
- [ ] **No single price → skip** ("price on request", auctions without a guide). Ranges are
      skipped unless `allow_price_range_midpoint: true`. Rentals are flagged (`is_rental`).
- [ ] **Credit line and link back working**: "Photos: {display_name}" under the carousel, and
      `listing_url` opens the original listing from the reveal screen.
- [ ] **The site is added to the About page** (it appears automatically once enabled; check the
      name and homepage link).
- [ ] **Tests** against saved fixture pages (no live requests in tests), including a check that
      descriptions/contact details on the fixture never reach the database.
- [ ] **Kill switch tested**: `enabled: false` + `python -m ingest deactivate --source <key>`
      removes it from play immediately.

## How to write a plugin — walkthrough of `example_html`

Files: `backend/ingest/sources/example_html.py` and the fixtures
`backend/tests/fixtures/example_search.html`, `example_listing.html`, `example_listing_2.html`.
Try it locally:

```bash
python -m http.server 8099 -d backend/tests/fixtures      # terminal 1: the fake site
backend/.venv/bin/python -m ingest run --source example_html   # terminal 2
backend/.venv/bin/python -m ingest stats --by source,images
```

(Its photo URLs point at the fictional `images.example.test`, so a live run marks them broken.
The tests use a stub image checker instead.)

1. **Plugin metadata.**
   ```python
   class ExampleHtml(SourcePlugin):
       key = "example_html"
       display_name = "Example Listings (fixture)"   # shown as "Photos: …" and on About
       homepage = "http://127.0.0.1:8099/"
       price_type = "asking"
       country_codes = ["PT", "HR"]
       image_hosts = ["images.example.test"]
   ```

2. **`discover()`**: fetch a search-results page with `client.get(...)` (never `httpx`
   directly) and yield listing URLs. `example_search.html` has `a.result-link` elements; real
   sites usually also have pagination (`a[rel=next]`). Respect `max_records_per_run`.

3. **`fetch_and_parse()`, JSON first.** Most sites embed the listing as JSON
   (`<script type="application/json">`, `__NEXT_DATA__`, JSON-LD). `example_listing.html` has
   `script#listing-data`. Read only the fields you need: id, price, type, area, rooms, year,
   city/region/country, `geo` and `photos`. The same blob also contains `agent`,
   `description` and `address.street`: **ignore them**.

4. **HTML fallback.** `example_listing_2.html` has no JSON: read `.price`, `.facts li`,
   `.locality[data-city]`, the map widget's `data-lat`/`data-lng`, and `.gallery img`.

5. **Normalize.**
   - Price: `parse_price(text, default_currency, allow_range_midpoint=…)` handles `€ 340.000`,
     `R$ 1.050.000`, `3,800万円`, `1,280萬` (pass `"TWD"` as the default), `$1.2M`. It returns
     `None` for "price on request" and ranges, so return `None` too (the listing is skipped).
   - Prices in HRK are fine: the pipeline converts kuna to euro at 7.53450.
   - Area: `parse_area("1,615 sq ft")` → 150.0 m².
   - Type: `normalize_property_type("Apartamento")` → `apartment`.
   - `price_date`: the sold date if the listing shows one (`price_type="sale_record"`),
     otherwise today (the pipeline keeps the first-scraped date while the price is unchanged).

6. **Coordinates: only the listing's own.** From the JSON or the site's map widget. If the site
   blurs them (many do), set `location_precision="approximate"`. If there are none, leave
   `lat`/`lng` as `None`: the home is stored but not playable (setting `unknown`). **Never call a
   geocoder.**

7. **Photos.** Build `NormalizedImage(url, width, height, kind)` in the listing's order, absolute
   `https://` URLs on your `image_hosts`. If the site offers size variants
   (`data-src` 800 px / `data-src-large` 1600 px), pick the largest published ≤ 1600 px. Label
   floor plans `kind="floorplan"` when the site does (they're shown last). At least 2 photos are
   required.

8. **Register** it in `backend/ingest/sources/__init__.py` and **configure** it in
   `backend/ingest/sources.yaml` with `enabled: false`:
   ```yaml
   my_site:
     enabled: false
     delay_seconds: 5
     image_delay_seconds: 1
     max_records_per_run: 50
     image_hosts: ["img.my-site.example"]
     allow_price_range_midpoint: false
   ```

9. **Test** with saved fixture pages and the `fixture_site` pytest fixture (a local HTTP server),
   as in `backend/tests/test_ingest_example_html.py`. Assert prices, coordinates, photo order,
   and that no description or contact details were stored.

10. **Tick the checklist, enable, do a small first run**, then regenerate the CSP:
    ```bash
    make ingest ARGS="run --source my_site --limit 10"
    make ingest ARGS="stats --by source,images"
    make csp      # adds the new image_hosts to the Content-Security-Policy (make up does this too)
    ```

## What the pipeline does with every listing

`discover` → blocklist check → `fetch_and_parse` → launch-country whitelist → HRK→EUR → FX to
USD at `price_date` → validation (price $5k–$100M, area 10–50,000 m², $50–$100k per m², rent
check, ≥ 2 photos, photo hosts allowed, listing URL present) → urban/rural from GHSL (needs the
listing's coordinates) → upsert on `(source, source_ref)` → photo URLs stored (≤ 10) and
verified (`HEAD`, image/*) → cross-source duplicate kept out of the pool. Each run writes an
`ingest_runs` row. A home is playable once it has ≥ 2 working photos.

Afterwards:
- `ingest images-check` re-verifies unchecked or stale photo URLs.
- `ingest refresh` (daily) re-fetches listings not seen for 14 days: delisted → inactive, photos
  re-checked; asking listings gone 30+ days are deleted with their photo URLs.

## When a source blocks us

A 403, 429 or challenge page (pages **or** images) stops that source's run immediately; it's
logged as `BLOCKED` and recorded with `status='blocked'`. Records saved before the block are
kept. Don't retry until the next scheduled run; if it keeps happening, disable the source. Never
work around it: no proxies, header spoofing, headless browsers or referrer tricks.

## Removals and reports

- **Removal requests** (About page form): `python -m ingest removals`, then
  `python -m ingest remove --property-id <uuid> --request <#>`. That deactivates the home,
  deletes its photo URLs and blocklists it. Act within 72 hours.
- **Player photo reports**: `python -m ingest reports`. A `price_visible` report removes the home
  from play until handled: `--resolve <#> --action dismiss|drop-photo|remove`.
- **Whole source**: set `enabled: false` in `sources.yaml` and run
  `python -m ingest deactivate --source <key>`.
