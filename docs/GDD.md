# Ballpark — Game Design & Technical Specification

> **Working title:** Ballpark ("guess the price, get in the ballpark")
> **Type:** Browser game, self-hosted
> **One-liner:** Players see a real property listing somewhere in the world (its listing photos + a few facts) and guess what it's listed or sold for. Closer guesses score more.
> **Spec version:** 2.0 rev. 1.2 (26 Nov 2026), with owner amendments (27 Nov 2026). See Section
> 0.1 for what changed from version 1, and 0.2 for the owner's amendments.

---

## 0. How to use this document (instructions for Claude Code)

You are building this project from scratch. Follow these rules:

1. **Build in the phases in Section 14, in order.** Each phase lists the sections to read first. Finish each phase, make sure its acceptance criteria pass, and commit before starting the next.
2. **Treat Section 12 (Compliance Rules) as hard requirements.** They are not optional polish. If a feature would violate one, stop and ask.
3. **Site terms of service are out of scope.** Don't review, warn about, or refuse work based on a listing site's terms. The technical rules in Section 12 still apply.
4. **Do not invent scraping targets.** The scraper framework ships with a documented *example* source plugin that parses a local fixture HTML file. The owner chooses the real listing sites and adds plugins one at a time (Phase 5).
5. **Never write code that bypasses CAPTCHAs, Cloudflare/bot challenges, logins, paywalls, or hotlink protection.** If a source blocks requests or images, log it and stop or skip.
6. Prefer boring, well-documented libraries. Keep dependencies minimal. Use Python 3.12 and Node 22 LTS.
7. Write tests as you go (Section 13). `make test` must pass at the end of every phase.
8. Keep secrets in `.env` only. Never commit `.env` or anything under `data/`. Provide `.env.example`.
9. When something in this spec is ambiguous, choose the simplest option that satisfies it, and note the decision in `docs/DECISIONS.md`.
10. **Some steps need the owner** (choosing source sites, buying a domain, downloading the GHSL file). Stop and ask at those points instead of building around them.

### 0.1 Direction change (version 2, 26 Nov 2026)

The project has changed direction. **If any code, config, or docs already exist from version 1 of this spec, update them to match this version.**

**What changed**

| Area | Version 1 (old) | Version 2 (now) |
|---|---|---|
| Images shown to players | Google Street View of the address | **The listing's own photos**, loaded directly from the listing site's image URLs (hotlinked) |
| Google Maps Platform | Street View Static API, metadata API, URL signing, quota counter | **Removed completely.** No Google API keys, no Google requests, no Google content of any kind |
| Property data sources | Open government sale records (UK Land Registry, France DVF, etc.) plus listing sites | **Listing sites only.** All property data (price, facts, location, photos) comes from the listing itself |
| Location | Geocoded with Nominatim / postcodes.io | **Only coordinates the listing provides.** No geocoding services |
| First real data source | UK Price Paid importer | None built in. The owner picks the first listing site (Phase 5) |

**Why:** the owner wants players to see the actual listing photos, which are more fun and more informative than street views. Government sale records have no photos and Street View is no longer needed, so both are dropped.

**Still used (not property data):**
- ECB exchange rates via Frankfurter (6.5) for USD conversion
- The GHSL settlement raster (8.9), an offline file used only to label listings urban/suburban/rural from the listing's own coordinates
- OpenStreetMap tiles for the optional mini map (4.2)

**Migration notes for existing v1 code:**
- Delete `streetview.py`, `streetview_urls.py`, `uk_price_paid.py`, `geocode.py`, the `sv_usage` table, all `GOOGLE_*` and `NOMINATIM_URL` settings, the Street View quota logic, and the Google attribution UI
- Drop the `pano_id` and `sv_status` columns. Add the `property_images` table and `images_status` column (5.1)
- Replace `StreetViewImage` with `PhotoCarousel` in the frontend
- Write an Alembic migration for the schema change. Don't edit old migrations

**Risk the owner has accepted:** listing photos are copyrighted by photographers, agents, or the listing sites, and real estate companies do sue over photo use. Rules 12.1–12.6 are there to keep that risk as low as possible: hotlink only, never copy or modify, credit the source, link back, remove on request, and keep it non-commercial. Do not weaken them.

### 0.2 Owner amendments (27 Nov 2026)

These answer the open questions in Section 15 and override the text below where they conflict.
Details are in `docs/DECISIONS.md`.

| Topic | Amendment |
|---|---|
| Neighbourhoods (2.5, 4.1, 4.5, 5.3, 5.4, 9.3) | **Two categories: Urban and Rural.** Suburbs count as Urban (GHS-SMOD codes 21–30 → urban). Instead of Urban/Suburban mode cards, the Home screen has **Urban / Rural toggles**, both on by default; at least one stays on. Default, Classic and Daily games use Urban + Rural. Leaderboards are kept per combination (`setting_filter` = `rural,urban`, `urban` or `rural`) |
| Daily data (Q3) | Both asking prices and recorded sale prices |
| Timer / extra-hard (Q4) | Neither |
| Rural (Q5) | Played, as one of the two toggles |
| Floor plans (Q6) | Shown, at the **end** of the carousel (after the photos) |
| Name, domain, colour (Q1, Q2) | Unchanged for now ("Ballpark", placeholder domain, burnt-orange accent) |

---

## 1. Game overview

### 1.1 Core loop
1. Player starts a game (5 rounds by default).
2. Each round shows:
   - The listing's photos in a swipeable carousel (up to 6, in the listing's own order)
   - Clues: country, city/region, setting (urban / suburban / rural), property type, size (m² and ft²), bedrooms, bathrooms, year built (when listed), listing/sale year
   - A small map pin showing roughly where it is (city-level zoom), only when the listing provides coordinates
   - A photo credit line: "Photos: {source name}"
3. Player enters a price guess. In **Normal** difficulty the guess is in USD. In **Hard** difficulty it must be in the property's local currency (see 2.6).
4. Reveal screen: actual price, the guess, % off, points earned, price per m², and a "See original listing" link.
5. After 5 rounds: total score, per-round breakdown, shareable result text, optional leaderboard submission.

### 1.2 Design pillars
- **Surprise:** "THAT costs €2.1M?" moments. Mix cheap and expensive, many countries, apartments and houses.
- **Fairness:** Scoring is proportional (log-based), so a $5M mansion and a $60k cabin are equally hard.
- **Speed:** A full game takes 2–4 minutes. No account required to play.
- **Respect for sources:** Photos are shown exactly as published, always credited and linked back, never copied to our servers, and removed fast on request.

### 1.3 Target platforms
- Desktop and mobile browsers (responsive, mobile-first layout)
- No native apps

### 1.4 Launch countries
The game launches with exactly these 16 countries (full details in Section 5.5). The ingestion pipeline must reject listings from any other country.

| Region preset | Countries |
|---|---|
| North America | United States, Canada, Mexico |
| South America | Brazil |
| Europe | Portugal, Spain, United Kingdom, France, Italy, Poland, Croatia |
| Africa | South Africa |
| Oceania | Australia, New Zealand |
| East Asia | Japan, Taiwan |

---

## 2. Game modes

### 2.1 Classic (MVP)
- 5 random rounds from the global pool (or a chosen region)
- Max 5,000 points per round → 25,000 per game

### 2.2 Daily Challenge (MVP)
- Same 5 properties for every player on a given UTC date
- One scored attempt per device per day (enforced softly via localStorage + server-side device ID)
- Daily leaderboard
- Shareable emoji result (see 6.4)

### 2.3 Regional (Phase 4)
- Player picks **World**, one of the region presets in 1.4, or a **single country** from the 16
- Otherwise identical to Classic
- An option is only selectable if the matching pool has ≥ 50 eligible properties (counts come from `GET /api/meta`). Otherwise it's greyed out with "Coming soon"

### 2.4 Higher / Lower (Phase 4)
- Two properties side by side, each with its lead photo; the player picks which costs more (compared in USD)
- Endless; streak counter; one wrong answer ends the run
- Leaderboard by best streak

### 2.5 Urban mode and Suburban mode (Phase 3) — *superseded by 0.2: Urban/Rural toggles*
- Two dedicated modes on the Home screen: **Urban** (city centers and dense neighborhoods) and **Suburban** (suburbs, outer neighborhoods, edges of towns)
- Each is a preset of Classic with a `setting` filter, and it can be combined with a region/country and either difficulty
- **Default setting is Urban + Suburban.** Classic, Regional, and Daily games use both together. Rural and `unknown` properties are kept in the database but not played at launch (see open question 5)
- How each property's setting is classified is in Section 8.9
- Each mode has its own leaderboards (see 4.5)

### 2.6 Difficulty: Normal vs Hard (local currency)
Difficulty is a toggle chosen before any Classic, Regional, Urban, Suburban, or Daily game. It's locked once the game starts. **The default is Normal (USD).** Hard is always opt-in.

| | Normal | Hard |
|---|---|---|
| Guess currency | USD | Property's local currency only (EUR, JPY, BRL, …) |
| USD shown during the round | yes | **no**, nowhere on screen |
| Currency toggle | none | none |
| Slider range | $5,000 – $50,000,000 | the same USD range converted to local currency and rounded to "nice" numbers (e.g., ¥750,000 – ¥7,500,000,000) |
| Helper text | none | currency name + symbol only, e.g., "Japanese yen (¥)". **No exchange rate hint** |
| Reveal screen | local + USD | local first, then USD, plus "1 USD ≈ X JPY" as a learning moment |
| Scoring | Section 3.1 | **identical formula**, computed in local currency |
| Leaderboards | Normal boards | separate Hard boards |
| Share text | normal | adds a 🔥 HARD tag |

- Higher/Lower supports Hard too: prices are revealed in each property's own currency after picking, and the comparison is still done in USD behind the scenes.
- First visit: Normal (USD) is selected. After that, remember the player's last choice in localStorage. If storage is unavailable, fall back to Normal.

### 2.7 Future ideas (not in scope, don't build)
- Real-time multiplayer rooms
- "Price per m²" mode
- Custom game links with chosen settings

---

## 3. Scoring

### 3.1 Classic / Daily / Regional / Urban / Suburban
Score is based on the log ratio between guess and actual price, so being 2× too high is penalized the same as being 2× too low.

```
error  = |ln(guess / actual)|
score  = round(5000 × max(0, 1 − error / ln(3)))
```

- Exact guess → 5000
- Off by ±10% → ~4,566
- Off by 2× → ~1,845
- Off by 3× or more → 0
- Always compare in the **same currency**. Normal: convert the USD guess to local currency using the property's stored `fx_rate_to_usd` before scoring. Hard: the guess is already local.
- Difficulty does not change the formula. Hard is harder because players have to know currency values, and it gets separate leaderboards.
- Guess must be > 0. Reject non-numeric input on both client and server.

Make `MAX_POINTS` (5000) and `ZERO_POINT_RATIO` (3) config constants.

### 3.2 Reveal labels
| Error (% off) | Label |
|---|---|
| ≤ 5% | "Bullseye!" |
| ≤ 15% | "In the ballpark" |
| ≤ 35% | "Close-ish" |
| ≤ 100% | "Way off" |
| > 100% | "Different planet" |

### 3.3 Higher / Lower
- +1 per correct pick. If the two USD prices are within 3% of each other, either answer counts as correct.

---

## 4. Player experience & screens

### 4.1 Home
- Title, short tagline
- Mode cards: "Classic" (subtitle: Urban + Suburban, the default and most prominent card), "Urban", "Suburban", "Daily Challenge" (shows ✓ if done today), later "Higher / Lower"
- A settings row above the mode cards that applies to whichever mode is started:
  - **Where:** World (default) / region preset / single country (dropdown grouped by region, with flag emoji and country name)
  - **Difficulty:** **Normal (USD)** (default) / Hard (local currency) as a segmented control, with a short tooltip explaining Hard
- "Leaderboards", "How it works / About"
- Daily Challenge ignores the "Where" setting (it's always World, Urban + Suburban) but respects difficulty
- Footer: "Photos and listing data belong to their sources", source credits, "Request removal" link

### 4.2 Round screen
- **Top bar:** round X/5, running score, and a mode badge, e.g. "Urban · Europe · 🔥 Hard"
- **Main: `PhotoCarousel`**
  - Shows the listing's photos (up to `MAX_PHOTOS_PER_ROUND`, default 6) in the order the listing uses. The first photo is the listing's lead photo
  - Swipe on mobile, arrow buttons and ←/→ keys on desktop, dot indicators, tap to view full screen
  - `<img>` tags load **directly from the listing site's image URL** (hotlinking). Use `loading="lazy"` for photos after the first. Don't set `referrerpolicy` or anything else meant to get around hotlink protection
  - Display photos exactly as published: no cropping that hides part of the photo (use `object-fit: contain` on a neutral background), no filters, no overlays covering any part of the photo, and **never hide or remove watermarks**
  - Credit line under the carousel: "Photos: {source name}". The source name doesn't reveal the price, so it's shown during the round
  - A small "Report photo" link (e.g., "the price is visible in this photo," "broken image," "shows a person") → `POST /api/reports`
  - If a photo fails to load, skip it silently. If every photo fails, show a placeholder card ("Photos unavailable"), let the player continue, and log it (see 7.4)
- **Clue chips** below or beside the carousel
- **Mini map:** OpenStreetMap tiles via Leaflet at city-level zoom (~zoom 10), with a pin slightly offset so it doesn't pinpoint the home. Only shown when the listing provided coordinates
- **Guess input:**
  - Numeric text field with thousands separators as the user types, plus the currency symbol (USD in Normal, local in Hard)
  - Accept the shorthand suffixes `k`, `m`, and `b` (e.g., "450k", "1.2m")
  - Log-scale slider underneath, synced with the text field: `value = min × (max/min)^t` for slider position `t` in [0,1]. The range depends on difficulty (see 2.6)
  - Currencies with no minor units (JPY, TWD in practice) and very large numbers must format correctly. Use `Intl.NumberFormat(userLocale, {style: 'currency', currency, maximumFractionDigits: 0})`
  - "Lock in guess" button (also Enter key)
- **No timer in MVP.** (Optional 60s timer setting later.)

### 4.3 Reveal screen (per round)
- Actual price in local currency and USD, the guess, % off, points, label
- Whether it's an asking price or a recorded sale price
- Animated bar or number counting up to the score
- Facts: price per m² and price per ft², listing/sale date, source name
- **"See original listing" button** (opens a new tab). Every playable property has one
- "Next round" button

### 4.4 Game summary
- Total score, and a row per round with the lead photo as a small thumbnail (hotlinked, same rules as 4.2), city, actual, guess, and points
- Share button → copies text (see 6.4); uses the Web Share API on mobile when available
- "Submit to leaderboard" with a nickname (3–16 chars, profanity filtered with a simple word list)
- "Play again"

### 4.5 Leaderboards
- **Mode** tabs: Daily, Classic, Urban, Suburban, Higher/Lower
- **Difficulty** filter: Normal / Hard (always kept separate, never mixed)
- **Where** filter: World (default) / region preset / country. Entries are stored with the exact settings the game was played with, and boards only show entries that match exactly
- **Period** filter: Today / 7 days / All time (Daily only has Today and past dates)
- Show rank, nickname, score, a country flag for the game's "Where" setting, and the date

### 4.6 About / Data & Removal
- Explains that all properties come from public listing sites, that photos and listing data belong to their owners, and that prices may be asking prices or recorded sale prices
- Lists every enabled source with a link
- Says photos are shown directly from the source and never copied to our servers
- **Removal request form** for owners, agents, photographers, and sites (email + listing URL or property ID + message) → stored in DB, shown in the admin CLI. Promise action within 72 hours
- Credits for the GHSL dataset (8.9), exchange rates (6.5), and OpenStreetMap

### 4.7 Visual style
- Clean, warm, slightly playful. Off-white background, one strong accent color, rounded cards. The photos are the star, so keep the UI around them quiet
- Large, readable numbers (tabular figures for prices)
- Dark mode via `prefers-color-scheme`
- Accessible: keyboard playable, visible focus states, color is never the only signal, alt text on photos ("Listing photo 2 of 6, property in Lyon, France")

---

## 5. Content & data rules

### 5.1 Data model

**`properties`**

| Field | Required | Notes |
|---|---|---|
| id | yes | internal UUID |
| source_id | yes | FK to sources |
| source_ref | yes | the listing's ID or URL on the source; used for dedupe and removal |
| listing_url | yes | public link back; sent to the client only in the reveal |
| price_type | yes | `asking` (listing price) or `sale_record` (the listing shows a sold price) |
| price_local | yes | integer, smallest whole unit (e.g., 425000) |
| currency | yes | ISO 4217 (USD, EUR, GBP, JPY…) |
| price_usd | yes | converted at the FX rate on price_date |
| fx_rate_to_usd | yes | stored for auditability |
| price_date | yes | sold date if the listing shows one, otherwise the date first scraped |
| country_code | yes | ISO 3166-1 alpha-2 |
| region | no | state/province/county, from the listing |
| city | yes | from the listing |
| lat, lng | no | **only** if the listing itself provides them (page data, embedded JSON, map widget). Never geocoded |
| location_precision | no | `exact`, `approximate` (many sites deliberately blur locations), or null when there are no coordinates |
| setting | yes | `urban`, `suburban`, `rural`, `unknown`; computed at ingestion (8.9). `unknown` when there are no coordinates |
| setting_class_raw | no | raw classifier code, kept for debugging and reclassification |
| property_type | yes | `house`, `apartment`, `townhouse`, `land`, `other` |
| area_m2 | no | store metric; convert for display |
| bedrooms, bathrooms | no | |
| year_built | no | |
| images_status | yes | `unchecked`, `ok`, `broken` |
| images_checked_at | no | last time the photo URLs were verified (8.7) |
| is_active | yes | false = excluded from play |
| last_seen_at | yes | last time a scrape found the listing still live |
| created_at, updated_at | yes | |

**`property_images`**

| Field | Required | Notes |
|---|---|---|
| property_id | yes | FK |
| position | yes | 0 = lead photo, in the listing's order |
| url | yes | absolute HTTPS URL of the image **as published by the source**. We store the URL only, never the image file |
| width, height | no | if the source provides them (helps layout) |
| kind | no | `photo` or `floorplan` if the source labels it; otherwise null |
| status | yes | `ok`, `broken` |

- Unique (property_id, position). Keep at most `MAX_PHOTOS_STORED` (default 10) per property; show up to `MAX_PHOTOS_PER_ROUND` (default 6).

### 5.2 What is NEVER stored or done
- **Image files.** No downloading photos to disk, no caching them, no proxying them through our server, no thumbnails, no resizing, no CDN copies. Only the URLs are stored
- **Modified photos.** No cropping, editing, watermark removal, or AI upscaling
- Agent/owner/photographer names, phone numbers, emails, or free-text listing descriptions
- Exact street addresses (keep only city/region and the listing's own coordinates)
- Any data from Google Maps Platform, or from geocoding services

### 5.3 Eligibility for play
A property is playable only if:
- `is_active = true` and `images_status = 'ok'`, with **at least 2** photos with `status = 'ok'`
- `country_code` is one of the 16 launch countries
- `listing_url` is present
- `price_usd` is between $5,000 and $100,000,000
- `price_date` is no older than `MAX_PRICE_AGE_YEARS` (config, default 2, since asking prices go stale fast)
- it isn't in the removals list or blocklist and has no open "price visible in photo" report
- `setting` is `urban` or `suburban` (default games use both; Urban/Suburban modes use only their own). `rural` and `unknown` aren't played at launch, so in practice **listings need coordinates to be playable**

### 5.4 Pool balancing
When picking rounds for Classic/Daily:
- No two rounds from the same city in one game
- At most 2 rounds from the same country (when the World pool is used)
- Aim for a spread of price bands: pick from log-price quintiles, at least 3 different quintiles per game
- At most 3 rounds from the same source in one game, when the pool allows
- Never repeat a property for the same device within its last 20 games (soft; best-effort via device ID)
- **Country weighting for World games:** pick a country first (equal weight per country among those with ≥ 50 eligible properties), then a property within it, so countries with more scraped listings don't dominate
- In single-country games the "≤ 2 per country" rule is ignored, but the city rule is kept where possible (relax it if the country has fewer than 5 cities in the pool)
- In default (Urban + Suburban) games, include at least 2 urban and 2 suburban rounds when the pool allows
- Daily Challenge picks: prefer properties whose photos were verified in the last 48 hours (8.7)

### 5.5 Launch countries & currencies

All property data comes from listing sites the owner chooses. Site terms of service are out of scope for this project: don't check them, flag them, or block on them. Before a source is enabled it only has to pass the technical checklist in 12.9.

| Country | ISO | Currency | In ECB/Frankfurter FX? | Notes |
|---|---|---|---|---|
| United States | US | USD | base currency | Huge variety; weight by state so one city doesn't dominate |
| Canada | CA | CAD | yes | |
| Mexico | MX | MXN | yes | Prices are sometimes listed in USD. Store the currency the listing uses |
| Brazil | BR | BRL | yes | Many apartments |
| Portugal | PT | EUR | yes | |
| Spain | ES | EUR | yes | |
| United Kingdom | GB | GBP | yes | Watch for "offers over" and "guide price" wording. Store as asking |
| France | FR | EUR | yes | |
| Italy | IT | EUR | yes | |
| Poland | PL | PLN | yes | |
| Croatia | HR | EUR | yes | Euro since 1 Jan 2023. Convert any listing still in HRK at the fixed rate 7.53450 HRK = 1 EUR and store as EUR |
| South Africa | ZA | ZAR | yes | |
| Australia | AU | AUD | yes | Many listings show a price range or "auction" with no price. Skip listings without a single price; use the midpoint only if the plugin's config allows it |
| New Zealand | NZ | NZD | yes | Same as Australia: auction/"by negotiation" listings often have no price, so skip them |
| Japan | JP | JPY | yes | Prices are often written in 万円 (10,000-yen units), so normalize carefully |
| Taiwan | TW | TWD | **no** | FX needs the fallback provider (6.5). Prices are often in 萬 (10,000 units) |

- Store this table as data in `backend/app/core/countries.py` (code, name, flag emoji, currency, region preset, default locale). Nothing else in the codebase should hard-code country lists.
- `GET /api/meta` returns each country with its eligible counts per setting, so the UI can disable empty options.
- **Launch target:** ≥ 200 eligible properties per country, with ≥ 50 urban and ≥ 50 suburban where possible. Countries below 50 eligible properties stay hidden until they have enough.

---

## 6. Systems

### 6.1 Sessions & anti-cheat (light touch)
- The client never receives the price before submitting a guess.
- `POST /api/games` creates a game server-side, picks the properties, and returns a `game_id` plus round 1 data only.
- `POST /api/games/{game_id}/rounds/{n}/guess` scores the guess, returns the reveal data, and unlocks round n+1.
- The listing URL is only sent in the reveal response (it can contain the price).
- Rounds must be answered in order; a round can't be re-guessed.
- Leaderboard submissions are accepted only for completed games, using the server-computed score.
- Rate-limit game creation per IP (e.g., 30/hour) and guesses (e.g., 120/hour).
- **Known limitation:** photo URLs point at the source site, so a determined player could reverse-image-search a photo to find the listing. That's acceptable for a casual game. Don't proxy images to hide it (that would break rule 12.1).

### 6.2 Device identity
- On first visit, generate a random UUID and keep it in localStorage (`ballpark_device_id`). Wrap localStorage reads and writes in try/catch.
- Send it as a header `X-Device-Id`. It's used only for daily-attempt limits and repeat avoidance. No accounts in MVP.

### 6.3 Daily challenge generation
- A scheduled job at 00:05 UTC creates `daily_challenges(date, property_ids[5])` using the pool rules plus a deterministic seed (`sha256(date + DAILY_SALT)`).
- Right before saving, re-verify the photo URLs of the 5 chosen properties (8.7). Replace any that fail.
- If the job didn't run, generate lazily on the first request of the day (with a DB lock so it only happens once).

### 6.4 Share text
```
Ballpark Daily #142 — 18,420 / 25,000
🟩🟩🟨🟥🟩
ballpark.example.com
```
- 🟩 ≥ 4000, 🟨 2000–3999, 🟧 1–1999, 🟥 0
- The daily number is the count of days since launch date (config value).

### 6.5 Currency
- FX source: the European Central Bank reference rates (free). Fetch the historical daily rates via the Frankfurter API (`api.frankfurter.app`), or download the ECB CSV directly. Cache the rates in an `fx_rates` table.
- Convert at ingestion using the rate for `price_date` (nearest earlier business day).
- Currencies the ECB doesn't cover (**TWD** among the launch countries): use a pluggable `FallbackFxProvider`. The default implementation reads monthly average rates from a CSV the owner maintains (`data/fx_manual.csv`: `month,currency,rate_to_usd`). A provider for an official source such as the Central Bank of the Republic of China (Taiwan) can be added later. If no rate exists for a record's month, skip the record and log it.
- Display: format with `Intl.NumberFormat` using the currency code. Normal mode shows USD during play and local + USD on reveal. Hard mode follows 2.6.
- Hard-mode slider bounds: `USD_MIN × rate` and `USD_MAX × rate`, rounded to 1, 2, or 5 × 10ⁿ. Use the most recent FX rate for the currency, and cache it in memory for the day.

### 6.6 Units
- Store metric. Display both: "120 m² (1,292 ft²)". 1 m² = 10.7639 ft². Convert ft² listings to m² at ingestion.

---

## 7. Listing photos

### 7.1 How photos are handled
- Each source plugin extracts the listing's photo URLs in the listing's order (from the page HTML, an embedded JSON blob, or the site's own data request).
- Prefer the largest size the listing itself publishes that's ≤ ~1600 px wide. If the site offers size variants in its URLs, the plugin may choose among the sizes the site already serves, but must not request sizes the site doesn't publish.
- Store only the URLs in `property_images` (5.1). Image bytes are never written to disk or a database.
- The browser loads photos directly from the source's image host.

### 7.2 Ingestion check
- After a listing is parsed, verify its photo URLs with the PoliteClient (8.2): a `HEAD` request, or a `GET` whose body is discarded immediately if the host doesn't support `HEAD`.
- Mark a photo `ok` if the response is 200 with an `image/*` content type, otherwise `broken`.
- Set the property's `images_status` to `ok` if ≥ 2 photos are ok, otherwise `broken`.
- Image hosts count as their own domain for rate limiting and robots.txt checks.

### 7.3 Content Security Policy
- Each source in `sources.yaml` lists its `image_hosts` (e.g., `["images.example-listings.com"]`).
- The CSP `img-src` directive is generated from the enabled sources' `image_hosts` plus the OSM tile host. Photo URLs from any other host are rejected at ingestion.

### 7.4 Fallback & telemetry
- If photos fail to load on the client, the frontend reports it: `POST /api/telemetry/image-error {game_id, round_no, positions[]}`.
- The server marks those photos `broken`, and if fewer than 2 ok photos remain, marks the property `images_status='broken'` (not playable).
- Many listing sites use image URLs that expire or disappear when the listing is taken down. The refresh job (8.7) re-checks them.

---

## 8. Data ingestion (scraper framework)

### 8.1 Architecture
```
backend/ingest/
  cli.py                 # `python -m ingest ...` entry point
  config.py              # loads sources.yaml + .env
  http.py                # PoliteClient (see 8.2)
  robots.py              # robots.txt checking + caching
  models.py              # NormalizedListing + NormalizedImage dataclasses (match 5.1)
  normalize.py           # parsing helpers: prices (incl. 万/萬 units, "k"/"M"), areas, property types
  validate.py            # range checks, required fields, outliers
  fx.py                  # ECB/Frankfurter rate fetch + cache, TWD fallback, HRK conversion
  setting.py             # urban/suburban/rural classifier (Section 8.9)
  images.py              # photo URL verification (7.2) and refresh (8.7)
  pipeline.py            # discover → fetch → parse → normalize → validate → dedupe → upsert → verify images
  sources/
    base.py              # SourcePlugin abstract base class
    example_html.py      # reference plugin parsing tests/fixtures/example_listing.html
  sources.yaml           # enabled sources and per-source settings
```

### 8.2 PoliteClient requirements
- Honest User-Agent from config: `BallparkBot/1.0 (+https://<domain>/about; contact: <email>)`
- Checks robots.txt before every new path, including on image hosts. If disallowed → skip and log. Cache robots.txt for 24 h.
- Per-domain minimum delay (default 5 s for pages, 1 s for image checks, configurable per source, never below 1 s), plus random jitter of 0–2 s
- Max 1 concurrent request per domain
- On-disk HTTP cache for pages (e.g., `hishel` or a simple sqlite cache) so pages aren't refetched within `cache_ttl_hours` (default 72). **Never cache image responses**
- Retries: max 2, exponential backoff, only on 5xx/timeouts
- **On 403, 429, or a detected challenge page** (Cloudflare/CAPTCHA markers in the body): stop that source's run immediately, log `BLOCKED`, and do not retry until the next scheduled run. No proxy rotation, no header spoofing, no headless-browser evasion.
- Never sends cookies or credentials. Logged-out only.

### 8.3 SourcePlugin interface
```python
class SourcePlugin(ABC):
    key: str                 # "example_html"
    display_name: str        # "Example Listings"
    homepage: str
    price_type: Literal["asking", "sale_record"]
    country_codes: list[str]
    image_hosts: list[str]   # hosts the photo URLs may come from (7.3)

    @abstractmethod
    def discover(self, client, settings) -> Iterable[str]:
        """Yield listing URLs or IDs to fetch (e.g., from search result pages)."""

    @abstractmethod
    def fetch_and_parse(self, client, ref) -> NormalizedListing | None:
        """Return a normalized listing (facts + photo URLs only), or None to skip."""
```
- Plugins must only return fields in `NormalizedListing` / `NormalizedImage`. There are no fields for descriptions, contact info, or image bytes, so they can't be stored by accident.
- Coordinates: take them only from the listing (embedded JSON, map widget attributes, structured data). If the listing has none, leave lat/lng null. Don't call any geocoder.
- Skip listings with no single numeric price (e.g., "price on request," auctions without a guide price).
- `sources.yaml` example:
```yaml
example_html:
  enabled: false
  delay_seconds: 5
  max_records_per_run: 50
  image_hosts: ["images.example.test"]
  allow_price_range_midpoint: false
```

### 8.4 Example plugin (reference implementation)
- `example_html.py` parses `tests/fixtures/example_listing.html` and `tests/fixtures/example_search.html`, two fake pages written for the tests, with prices, facts, coordinates in an embedded JSON blob, and 8 photo URLs on `images.example.test`.
- It shows every pattern a real plugin needs: discovering listing links from a search page, reading embedded JSON, falling back to HTML selectors, normalizing price and area, and extracting ordered photo URLs.
- `docs/SOURCES.md` walks through it step by step as the template for real plugins.

### 8.5 Validation & cleaning
- Reject if: price_usd < 5,000 or > 100,000,000; area_m2 present and < 10 or > 50,000; price per m² < $50 or > $100,000 (likely bad parse); fewer than 2 photo URLs; a photo URL on a host not in `image_hosts`
- Rentals: reject anything that looks like a monthly rent (plugin flags it, plus a sanity check of price per m² against the country's typical range)
- Dedupe key: `(source_id, source_ref)`; also flag possible cross-source duplicates when lat/lng are within 15 m and the price is within 2%, and keep only one in the pool
- Normalize property types to the 5 allowed values

### 8.6 CLI commands
```
python -m ingest run --source example_html       # run one source
python -m ingest run --all                       # run all enabled sources
python -m ingest images-check --limit 500        # verify unchecked or stale photo URLs
python -m ingest refresh --older-than-days 14    # re-check listings still live + photos still loading
python -m ingest fx-update                       # refresh FX cache
python -m ingest stats --by country,setting      # counts by country/source/setting/images_status
python -m ingest reclassify-settings             # recompute urban/suburban/rural
python -m ingest deactivate --source example_html  # bulk-remove a source (takedown)
python -m ingest reports                         # list player photo reports
python -m ingest removals                        # list pending removal requests
python -m ingest remove --property-id <uuid>     # remove one record + its photo URLs, add to blocklist
```

### 8.7 Refresh & scheduling
- **Refresh job:** for active properties not checked in `REFRESH_DAYS` (default 14), re-fetch the listing page (cached rules apply). If the listing is gone (404/410 or the plugin says it's delisted), set `is_active=false`. Re-verify photo URLs and update their status. Update `last_seen_at`.
- Asking-price listings that have been gone for 30+ days are deleted, along with their photo URLs.
- Schedule (cron container or host cron):
  - `ingest run --all` weekly (Sunday 03:00 UTC)
  - `ingest images-check` after each run
  - `ingest refresh` daily at 04:00 UTC, limited to `REFRESH_DAILY_LIMIT` (default 500) listings
  - `fx-update` daily
  - Daily-challenge generation at 00:05 UTC

### 8.8 Country whitelist
- `pipeline.py` drops any listing whose `country_code` isn't in `countries.py`, and logs the count per run.

### 8.9 Urban / suburban / rural classification
Use the **GHSL Degree of Urbanisation settlement model (GHS-SMOD)** from the European Commission JRC. It's a free global raster (CC BY 4.0) that labels every 1 km grid cell. Download the latest epoch once (the owner runs `python -m ingest setting-data download`, or downloads it manually into `data/ghsl/`). It's an offline lookup using the listing's own coordinates. No data about listings is sent anywhere.

Map the GHS-SMOD level-2 codes to our setting:

| GHS-SMOD L2 code | Meaning | Our `setting` |
|---|---|---|
| 30 | Urban centre | urban |
| 23 | Dense urban cluster | urban |
| 22 | Semi-dense urban cluster | suburban |
| 21 | Suburban or peri-urban | suburban |
| 13 | Rural cluster | rural |
| 12 | Low density rural | rural |
| 11 | Very low density rural | rural |
| 10 / nodata | Water / no data | unknown |

Implementation:
- `setting.py` loads the raster with `rasterio`, transforms WGS84 lat/lng to the raster's CRS (Mollweide) with `pyproj`, samples the cell, and stores both `setting` and `setting_class_raw`
- Listings without coordinates get `setting='unknown'`
- Keep the dataset open once per ingest run. Sampling must be fast (thousands of points per second)
- **Adjustment rule:** an `apartment` in a code-30 cell stays urban. A `house` with area > 400 m² in a code-23 cell is reclassified to suburban (large detached houses inside dense clusters are usually edge-of-city). Keep this rule in one small function so the owner can tweak it
- If the GHSL file is missing, set `setting='unknown'` and log a warning instead of failing the run
- Add the GHSL citation to the About page

---

## 9. Technical architecture

### 9.1 Stack
| Layer | Choice |
|---|---|
| Frontend | Vite + React + TypeScript, CSS Modules (or plain CSS with variables), Leaflet for the mini map |
| Backend API | Python 3.12, FastAPI, Uvicorn |
| ORM / migrations | SQLAlchemy 2.x + Alembic |
| Database | SQLite in WAL mode (single-server self-hosting). Keep queries portable so Postgres can be swapped in later via `DATABASE_URL`. |
| Ingestion | Same Python project (`backend/ingest`), httpx, selectolax, optional Playwright **only** for sources that render listings with JavaScript and allow crawling |
| Reverse proxy / TLS | Caddy (automatic HTTPS) |
| Packaging | Docker + docker compose |
| Tests | pytest (backend), Vitest + React Testing Library (frontend), Playwright for one end-to-end smoke test |

### 9.2 Repository layout
```
ballpark/
  README.md
  CLAUDE.md                # short always-loaded rules for Claude Code (owner may add)
  Makefile                 # dev, test, lint, build, up, down, migrate, seed, e2e
  .env.example
  docs/
    GDD.md                 # this file
    DECISIONS.md
    SOURCES.md             # how to add a new source plugin, with compliance checklist
  backend/
    pyproject.toml
    app/
      main.py
      api/ games.py, daily.py, leaderboards.py, removals.py, reports.py, telemetry.py, health.py
      core/ config.py, db.py, security.py (rate limits, CSP builder), scoring.py, selection.py, countries.py
      models/ (SQLAlchemy models)
    ingest/  (see Section 8)
    alembic/
    tests/
      fixtures/ example_listing.html, example_search.html
  frontend/
    package.json
    src/
      main.tsx, App.tsx, api.ts, deviceId.ts, format.ts
      screens/ Home, Round, Reveal, Summary, Leaderboards, About
      components/ GuessInput, LogSlider, ClueChips, MiniMap, PhotoCarousel, PhotoCredit, ReportPhoto, ShareButton
      styles/
    public/
      demo-photos/         # placeholder images made for the demo seed data (original, not from any listing)
    tests/
  deploy/
    docker-compose.yml
    Caddyfile
    backup.sh
```

### 9.3 Database tables
- `sources(id, key, display_name, homepage, image_hosts JSON, enabled)`
- `properties(...)` and `property_images(...)` — see 5.1
- `fx_rates(date, currency, rate_to_usd)` — PK (date, currency)
- `games(id, mode, where_scope, where_value, setting_filter, difficulty, device_id, created_at, completed_at, total_score)`
  - `mode`: `classic`, `urban`, `suburban`, `daily`, `hl`
  - `where_scope`: `world`, `region`, `country`; `where_value`: e.g., `europe` or `JP`
  - `setting_filter`: `urban_suburban` (default), `urban`, `suburban`
  - `difficulty`: `normal` (default), `hard`
- `game_rounds(game_id, round_no, property_id, guess_amount, guess_currency, guess_local, score, answered_at)`
- `daily_challenges(date PK, property_ids JSON, created_at)` — the same 5 properties for both difficulties
- `daily_attempts(date, device_id, game_id)` — unique (date, device_id). One Daily per day regardless of difficulty
- `leaderboard_entries(id, game_id UNIQUE, mode, where_scope, where_value, difficulty, nickname, score, created_at)`, with an index on (mode, where_scope, where_value, difficulty, created_at)
- `hl_runs(id, device_id, difficulty, streak, created_at)` (Phase 4)
- `photo_reports(id, property_id, position, reason, device_id, status, created_at)` — reasons: `price_visible`, `broken`, `person`, `other`. A `price_visible` report removes the property from play until reviewed
- `removal_requests(id, email, reference, message, status, created_at)`
- `blocklist(source_id, source_ref)` — never re-ingest these
- `ingest_runs(id, source_key, started_at, finished_at, fetched, saved, skipped, blocked, errors)`

### 9.4 API (JSON, prefix `/api`)
| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /meta` | enabled sources, countries (from countries.py) with eligible counts per setting, region presets, daily number |
| `POST /games` `{mode, where_scope?, where_value?, difficulty?}` | create game → `{game_id, rounds_total, round: RoundPayload}`. Defaults: `where_scope=world`, `difficulty=normal`. `setting_filter` is derived from mode (`classic`/`daily` → `urban_suburban`). 422 if the pool has < 5 eligible properties for those settings |
| `POST /games/{id}/rounds/{n}/guess` `{amount, currency}` | → `{reveal: RevealPayload, next_round?: RoundPayload, summary?: SummaryPayload}`. **Server enforces the currency:** in Normal it must be `USD`, in Hard it must equal the property's local currency, otherwise 422 |
| `GET /daily` | today's status for this device (played? score? difficulty?) |
| `POST /daily/start` `{difficulty}` | like `POST /games` with mode=daily; 409 if already played today |
| `GET /leaderboards/{mode}?difficulty=&where_scope=&where_value=&period=day|week|all` | top 100 |
| `POST /leaderboards` `{game_id, nickname}` | submit a completed game |
| `POST /hl/next` / `POST /hl/answer` | Higher/Lower (Phase 4) |
| `POST /reports` `{game_id, round_no, position, reason}` | report a photo |
| `POST /removals` | removal request |
| `POST /telemetry/image-error` `{game_id, round_no, positions[]}` | flag broken photos |

`RoundPayload`: `{round_no, difficulty, guess_currency, slider: {min, max}, photos: [{url, width?, height?, alt}], photo_credit, clues: {country, country_code, flag, region?, city, setting, property_type, area_m2?, bedrooms?, bathrooms?, year_built?, price_year, price_type}, map?: {lat_approx, lng_approx}, local_currency}`

- `photos` contains only `status='ok'` photos, up to `MAX_PHOTOS_PER_ROUND`, in listing order.
- `photo_credit` = "Photos: {source display name}".
- `map` is omitted when the listing has no coordinates. `lat_approx/lng_approx` = coordinates rounded to 2 decimals (~1 km).
- `guess_currency` is `USD` in Normal and the local currency in Hard. The payload never includes an FX rate in Hard mode.
- The payload never includes the price, `listing_url`, or `source_ref`.

`RevealPayload`: `{price_local, currency, price_usd, price_type, guess_local, guess_usd, pct_off, score, label, price_per_m2_local?, price_date, source_name, listing_url, fx_hint}`

- `fx_hint` (e.g., `"1 USD ≈ 151 JPY"`) is included in every reveal and shown prominently in Hard mode.

### 9.5 Configuration (.env)
```
DATABASE_URL=sqlite:///./data/ballpark.db
DAILY_SALT=change-me
LAUNCH_DATE=2027-01-01
PUBLIC_BASE_URL=https://ballpark.example.com
CONTACT_EMAIL=you@example.com
SCRAPER_USER_AGENT=BallparkBot/1.0 (+https://ballpark.example.com/about; contact: you@example.com)
CORS_ORIGINS=http://localhost:5173
MAX_PRICE_AGE_YEARS=2
MIN_POOL_PER_OPTION=50
MAX_PHOTOS_STORED=10
MAX_PHOTOS_PER_ROUND=6
REFRESH_DAYS=14
REFRESH_DAILY_LIMIT=500
GHSL_SMOD_PATH=./data/ghsl/GHS_SMOD.tif
FX_MANUAL_CSV=./data/fx_manual.csv
OSM_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
```
No API keys are required to run the game.

---

## 10. Self-hosting & deployment

### 10.1 docker compose services
- `api`: FastAPI app (Uvicorn, 2 workers), mounts `./data` for SQLite
- `web`: built frontend served as static files by Caddy
- `caddy`: reverse proxy; `/api/*` → api, everything else → static frontend; automatic HTTPS for the configured domain; serves the generated CSP header (7.3)
- `cron`: lightweight container running the schedule in 8.7 (supercronic or a simple loop)

### 10.2 Hosting options (document all in README)
- Any small VPS (1 vCPU / 1–2 GB RAM is plenty, since photos aren't stored or served by us): Hetzner, DigitalOcean, Linode, Oracle free tier
- Or a home server / Raspberry Pi 4/5 with Cloudflare Tunnel or port forwarding
- Domain pointed at the server; Caddy handles certificates

### 10.3 Ops
- `deploy/backup.sh`: nightly SQLite backup using `sqlite3 .backup`, keeps 14 days
- Logs to stdout (docker logs); every ingest run also writes a row to `ingest_runs`
- `make up`, `make down`, `make logs`, `make migrate`, `make seed`

### 10.4 Local development
- `make dev` runs the API on :8000 with reload and Vite on :5173 with a proxy to the API
- `make seed` loads ~50 fake DEMO properties spread across all 16 countries. Their photos are simple original placeholder images in `frontend/public/demo-photos/` (e.g., generated SVG/PNG house illustrations with "DEMO" on them). **Never seed with real listing photos.** The game must be fully playable from seed data with no scraping

---

## 11. Performance, privacy & security
- Round creation < 300 ms server time
- Frontend bundle < 250 KB gzipped (excluding map tiles and photos)
- Photos: lazy-load all but the first; set width/height when known to avoid layout shift
- No third-party analytics in MVP. If added later, use a privacy-friendly self-hosted option
- Collect no personal data except: device UUID, optional nickname, removal-request email
- Security headers via Caddy: CSP (`img-src` from enabled sources' `image_hosts` + OSM tiles + `'self'`), HSTS, X-Content-Type-Options
- Input validation with Pydantic on every endpoint; parameterized queries only
- Escape any text that came from a listing (city, region) before rendering. Never inject listing HTML
- OSM tiles: follow the OpenStreetMap tile usage policy (attribution, valid referrer, low volume). The tile URL is configurable so another provider can be swapped in if traffic grows

---

## 12. Compliance rules (hard requirements)

1. **Hotlink only.** Listing photos are displayed from the source's own URLs. Never download, store, cache, proxy, resize, or re-host image files.
2. **Show photos as published.** No cropping that hides content, no edits or filters, no overlays on the photo, and **never remove or hide watermarks**.
3. **Credit and link back.** "Photos: {source}" is visible whenever photos are shown, and every reveal has a "See original listing" link.
4. **No personal data.** Never store agent/owner/photographer names, phone numbers, emails, free-text descriptions, or exact street addresses (enforced by the `NormalizedListing` schema).
5. **Fast removal.** Public removal form, `photo_reports`, CLI commands to remove a record or a whole source, and a blocklist so removed items never return. Act within 72 hours. Removing a property deletes its photo URLs too.
6. **Non-commercial at launch:** no ads, payments, or paid features. If monetization is ever considered, get legal advice first.
7. **Polite scraping:** robots.txt respected (pages and image hosts), per-domain delays, honest User-Agent, logged out, page caching, and stop on block. **No circumvention of any kind**, including hotlink protection.
8. **No Google and no geocoding.** No Google Maps Platform APIs or content, and no geocoding services. Coordinates come only from the listing.
9. `docs/SOURCES.md` must contain a checklist that every new source plugin has to pass before it's enabled:
   - robots.txt allows the listing and image paths
   - Works logged out, with no challenge pages
   - Delay ≥ 5 s for pages
   - Only schema fields extracted (facts + photo URLs + listing's own coordinates)
   - `image_hosts` set correctly
   - Credit line and link back working
   - The site is added to the About page
10. **Per-source kill switch:** setting `enabled: false` in `sources.yaml` and running `ingest deactivate --source <key>` must remove that source from play immediately.

---

## 13. Testing & acceptance

### 13.1 Backend unit tests
- Scoring: exact guess = 5000; 2× high and 2× low give equal scores; ≥3× = 0; currency conversion before scoring; a Normal USD guess and the equivalent Hard local guess score the same
- Countries: every entry in countries.py has a valid ISO code, currency, region preset, and flag; listings from other countries are dropped
- FX: TWD uses the fallback provider; HRK prices convert to EUR at 7.53450
- Setting classifier: known lat/lng points (use a tiny synthetic test raster, not the real GHSL file) map to the right setting; the adjustment rule works; missing coordinates or a missing raster give `unknown` without crashing
- Hard-mode slider bounds round to nice numbers for JPY, TWD, ZAR, PLN, and EUR
- Selection: no repeated city, ≤ 2 per country, ≤ 3 per source, price-band spread, eligibility filters (including ≥ 2 ok photos)
- PoliteClient: obeys robots.txt (use a local test server), enforces delays, stops on 403/429/challenge markers, never caches image responses
- Image verification: 200 + image/* → ok; 404, HTML responses, and disallowed hosts → broken; property status updates correctly
- Normalizers: price strings in many formats ("€ 340.000", "$1.2M", "£425,000", "¥38,000,000", "3,800万円", "1,280萬"), area units (m², ft², sqm), skipping "price on request" and ranges
- Example plugin: parses the fixture pages into the expected listings, coordinates, and ordered photo URLs
- Validation rejects outliers, rentals, and listings with < 2 photos
- The `NormalizedListing` schema has no description, contact, or image-bytes fields (a test that fails if someone adds one)

### 13.2 API tests
- Price, `listing_url`, and `source_ref` are never present in a RoundPayload; listing_url appears in every reveal
- RoundPayload photos are only `ok` photos, in order, capped at `MAX_PHOTOS_PER_ROUND`, and include the photo credit
- Hard mode: RoundPayload has no USD values or FX rate; a guess in the wrong currency → 422
- Urban/Suburban games only contain properties with the matching setting; default games contain only urban and suburban (never rural/unknown)
- `POST /games` with no difficulty or where_scope → a Normal (USD), World game
- Leaderboards never mix difficulties or "Where" settings
- Can't guess the same round twice or skip ahead
- Daily: second attempt from the same device → 409
- Leaderboard rejects incomplete games and uses the server score
- Image-error telemetry marks photos broken and removes the property from the pool when fewer than 2 remain
- A `price_visible` report removes the property from play
- No route serves, proxies, or redirects to image bytes

### 13.3 Frontend tests
- GuessInput formats numbers, accepts k/m/b, the slider and text stay in sync, and the log mapping round-trips
- The Normal/Hard toggle changes the input currency and slider range; Hard shows no USD anywhere on the round screen
- PhotoCarousel: shows photos in order, keyboard navigation works, broken images are skipped, the all-broken placeholder appears, and the credit line is always visible
- The country dropdown is grouped by region, and options with too few properties are disabled
- The full game flow renders with a mocked API

### 13.4 End-to-end smoke test (Playwright)
- With seed data: start Classic → swipe through photos → 5 guesses → summary shows 5 rows and a total → share text copied

---

## 14. Build phases & milestones

### Phase 1 — Playable skeleton (seed data, no scraping)
**Read first:** 0, 1, 2, 3, 4, 5.1–5.4, 6, 9, 10.4, 12
- Step 1: repo layout, Makefile, `.env.example`, DB models + migrations, `countries.py`
- Step 2: seed script with ~50 DEMO properties across all 16 countries (≥ 3 each, mixing urban/suburban/rural), with original placeholder photos (3–6 each)
- Step 3: scoring, selection, the games API (Classic), Normal and Hard difficulty
- Step 4: frontend Home (Where + Difficulty settings), Round (PhotoCarousel, clues, guess input), Reveal, Summary
- Step 5: docker compose + Caddy config
- **Done when:** `make dev` lets you play a full 5-round Classic game in both Normal and Hard, on desktop and mobile widths, and `make test` passes

### Phase 2 — Scraper framework
**Read first:** 5, 6.5, 7, 8, 12
- Ingest framework, PoliteClient, robots.txt, normalizers, FX (including the TWD fallback and HRK conversion), validation, country whitelist, CLI
- Photo URL verification (7.2) and the refresh job (8.7)
- GHSL setting classifier + `reclassify-settings` command
- `example_html` reference plugin + fixture pages
- `docs/SOURCES.md` with the compliance checklist and a "how to write a plugin" guide based on the example plugin
- **Done when:** `ingest run --source example_html` (pointed at the fixtures) loads the fixture listings with photos, coordinates, and settings, `ingest stats` shows them, and `make test` passes

### Phase 3 — Daily, modes & removal
**Read first:** 2.2, 2.5, 4, 6.3, 6.4, 7.3, 7.4, 9.4, 12
- Daily Challenge (Normal + Hard), share text with 🔥 HARD tag, leaderboards with mode/difficulty/where filters, nickname filter
- Urban and Suburban modes on Home, with their own leaderboards
- Mini map with OSM tiles (only when coordinates exist)
- CSP generated from `image_hosts`, image-error telemetry, Report photo, photo_reports
- About / Data & Removal page + removal form + CLI removal commands
- **Done when:** a Daily Challenge is playable end to end from seed data, reports and removals work, and the CSP blocks images from unlisted hosts

### Phase 4 — More modes & polish
**Read first:** 2.3, 2.4, 4.7, 10, 11
- Regional mode (region presets + single country), Higher/Lower mode (Normal + Hard)
- Animations, dark mode, accessibility pass (keyboard-only playthrough, screen-reader labels)
- Repeat-avoidance per device
- Backups, cron container, README deployment guide for VPS and home server
- **Done when:** deployed on a real domain over HTTPS with backups running

### Phase 5 — Owner-driven source expansion (ongoing)
**Read first:** 5.5, 7, 8, 12, docs/SOURCES.md
- The owner picks one listing site at a time and confirms it passes the SOURCES.md checklist. Only then does Claude Code help write its plugin
- Aim for at least one source per launch country. Track progress against the 5.5 launch target with `ingest stats --by country,setting`
- Countries stay hidden in the UI until they reach 50 eligible properties

---

## 15. Open questions for the owner (answered 27 Nov 2026, see 0.2)
1. Final game name and domain?
2. Accent color / visual vibe preference?
3. Should the Daily Challenge use only listings with sold prices (more "real") or asking prices too?
4. Any interest in a timer option, or an "extra hard" mode that shows only one photo and hides clues like size and bedrooms?
5. Should rural properties be added later, as their own mode or as an "include rural" option?
6. Should floor plans (when a source labels them) be shown in the carousel, or hidden?
