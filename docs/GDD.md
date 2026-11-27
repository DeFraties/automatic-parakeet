# Ballpark — Game Design & Technical Specification

> **Working title:** Ballpark ("guess the price, get in the ballpark")
> **Type:** Browser game, self-hosted
> **One-liner:** Players see a real property somewhere in the world (Street View + a few clues) and guess what it sold or is listed for. Closer guesses score more.

> **Owner changes since v1** (details in `docs/DECISIONS.md`):
> - 2026-11-27: default neighbourhoods are **urban + rural**, with urban / suburban / rural
>   toggles replacing the Urban and Suburban mode cards (§2.5).
> - 2026-11-27: **listing photos may be shown**, hotlinked from the source and never copied
>   (§5.1, §5.2, §12 rule 1). **Mapillary** street-level photos added as a free alternative to
>   Google Street View, which becomes optional (§7). Homes without any photo are playable with an
>   illustrated card (§5.3).

---

## 0. How to use this document (instructions for Claude Code)

You are building this project from scratch. Follow these rules:

1. **Build in the phases in Section 14, in order.** Finish each phase, make sure its acceptance criteria pass, and commit before starting the next.
2. **Treat Section 12 (Compliance Rules) as hard requirements.** They are not optional polish. If a feature would violate one, stop and ask.
3. **Do not invent scraping targets.** The scraper framework ships with (a) the UK HM Land Registry Price Paid importer and (b) a documented *example* source plugin against a local fixture HTML file. The owner will add real site plugins later, one at a time.
4. **Never write code that bypasses CAPTCHAs, Cloudflare/bot challenges, logins, or paywalls.** If a source blocks requests, the plugin must log it and stop.
5. Prefer boring, well-documented libraries. Keep dependencies minimal.
6. Write tests as you go (Section 13). `make test` must pass at the end of every phase.
7. Keep secrets in `.env` only. Never commit `.env`. Provide `.env.example`.
8. When something in this spec is ambiguous, choose the simplest option that satisfies it, and note the decision in `docs/DECISIONS.md`.

---

## 1. Game overview

### 1.1 Core loop
1. Player starts a game (5 rounds by default).
2. Each round shows:
   - A Street View image of the property (loaded live from Google)
   - Clues: country, city/region, setting (urban / suburban / rural), property type, size (m² and ft²), bedrooms, bathrooms, year built (when known), sale/listing year
   - A small map pin showing roughly where it is (city-level zoom)
3. Player enters a price guess. In **Normal** difficulty the guess is in USD. In **Hard** difficulty it must be in the property's local currency (see 2.6).
4. Reveal screen: actual price, the guess, % off, points earned, price per m², and a "See original listing" link when available.
5. After 5 rounds: total score, per-round breakdown, shareable result text, optional leaderboard submission.

### 1.2 Design pillars
- **Surprise:** "THAT costs €2.1M?" moments. Mix cheap and expensive, rural and urban, many countries.
- **Fairness:** Scoring is proportional (log-based), so a $5M mansion and a $60k cabin are equally hard.
- **Speed:** A full game takes 2–4 minutes. No account required to play.
- **Respect for sources:** Facts only, always link back, credit every photo, never copy one.

### 1.3 Target platforms
- Desktop and mobile browsers (responsive, mobile-first layout)
- No native apps

### 1.4 Launch countries
The game launches with exactly these 16 countries (full details in Section 5.5). The ingestion pipeline must reject records from any other country.

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
- Two properties side by side; player picks which cost more (compared in USD)
- Endless; streak counter; one wrong answer ends the run
- Leaderboard by best streak

### 2.5 Urban mode and Suburban mode (Phase 3)
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

### 3.1 Classic / Daily / Regional
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
- Footer: data source credits, "Request removal" link, Google attribution where required

### 4.2 Round screen
- **Top bar:** round X/5, running score
- **Main:** Street View image (640×640 max from the API; display responsively). Below or beside it: clue chips
- **Mini map:** OpenStreetMap tiles via Leaflet at city-level zoom (~zoom 10), with a pin slightly offset so it doesn't pinpoint the house. **Do not** use Google map tiles for this map. (Keeps Google content separate and avoids "non-Google map" issues.)
- **Guess input:**
  - Numeric text field with thousands separators as the user types, plus the currency symbol (USD in Normal, local in Hard)
  - Accept shorthand: "450k", "1.2m", "3億" is NOT required. Support `k`/`m`/`b` suffixes only
  - Log-scale slider underneath, synced with the text field: `value = min × (max/min)^t` for slider position `t` in [0,1]. The range depends on difficulty (see 2.6)
  - Currencies with no minor units (JPY, TWD in practice) and very large numbers must format correctly. Use `Intl.NumberFormat(userLocale, {style: 'currency', currency, maximumFractionDigits: 0})`
  - "Lock in guess" button (also Enter key)
- **Mode badge** in the top bar showing e.g. "Urban · Europe · 🔥 Hard"
- **No timer in MVP.** (Optional 60s timer setting later.)

### 4.3 Reveal screen (per round)
- Actual price in local currency and USD, the guess, % off, points, label
- Animated bar or number counting up to the score
- Facts: price per m² and price per ft², sale/listing date, source name
- "See original listing" link (opens new tab) when a URL exists
- "Next round" button

### 4.4 Game summary
- Total score, each round's thumbnail-less row (city, actual, guess, points)
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
- Explains where data comes from, that prices may be asking prices or recorded sale prices
- Lists every enabled source with a link
- Removal request form (email + listing URL or property ID + message) → stored in DB, shown in the admin CLI

### 4.7 Visual style
- Clean, warm, slightly playful. Off-white background, one strong accent color, rounded cards
- Large, readable numbers (tabular figures for prices)
- Dark mode via `prefers-color-scheme`
- Accessible: keyboard playable, visible focus states, color is never the only signal, alt text on images ("Street View of a property in Lyon, France")

---

## 5. Content & data rules

### 5.1 What a "property" record contains
| Field | Required | Notes |
|---|---|---|
| id | yes | internal UUID |
| source_id | yes | FK to sources |
| source_ref | yes | ID or URL on the source; used for dedupe and removal |
| listing_url | no | public link back; hidden until reveal |
| price_type | yes | `sale_record` (actual sale) or `asking` (listing price) |
| price_local | yes | integer, smallest whole unit (e.g., 425000) |
| currency | yes | ISO 4217 (USD, EUR, GBP, JPY…) |
| price_usd | yes | converted at the FX rate on price_date |
| fx_rate_to_usd | yes | stored for auditability |
| price_date | yes | sale date or date scraped |
| country_code | yes | ISO 3166-1 alpha-2 |
| region | no | state/province/county |
| city | yes | |
| lat, lng | yes | from the source or an open geocoder (NOT Google geocoding) |
| location_precision | yes | `exact` (building/address), `street` (street or address range), `district` (neighborhood/postcode area only) |
| setting | yes | `urban`, `suburban`, `rural`, `unknown`; computed at ingestion (Section 8.9) |
| setting_class_raw | no | raw classifier code, kept for debugging and reclassification |
| property_type | yes | `house`, `apartment`, `townhouse`, `land`, `other` |
| area_m2 | no | store metric; convert for display |
| bedrooms, bathrooms | no | |
| year_built | no | |
| pano_id | no | Google Street View panorama ID (allowed to be stored) |
| image_url | no | URL of the main listing photo **on the source** (hotlinked at play time; image bytes never stored) |
| mly_image_id, mly_status | no / yes | Mapillary image ID and check status (`unchecked`, `ok`, `none`) |
| sv_status | yes | `unchecked`, `ok`, `none` |
| is_active | yes | false = excluded from play |
| created_at, updated_at | yes | |

### 5.2 What is NEVER stored
- Image files (bytes) of any kind: listing photos are kept only as a URL on the source and loaded
  live by the player's browser (§12 rule 1)
- Google Street View images, Google geocoding results, or any Google content except `pano_id`
- Agent/owner names, phone numbers, emails, or free-text descriptions
- Exact street addresses (keep only city/region plus coordinates)

### 5.3 Eligibility for play
A property is playable only if:
- `is_active = true`, and, when `ALLOW_IMAGELESS_ROUNDS=false`, it has a photo (listing photo,
  Mapillary image or Street View panorama). By default homes without a photo are playable with an
  illustrated card, and selection prefers homes that have a photo
- `country_code` is one of the 16 launch countries
- `location_precision` is `exact` or `street` (otherwise Street View might show the wrong place)
- `price_usd` is between $5,000 and $100,000,000
- `price_date` is no older than `MAX_PRICE_AGE_YEARS` (config, default 5)
- it isn't in the removals list or blocklist
- `setting` is `urban` or `suburban` (default games use both; Urban/Suburban modes use only their own). `rural` and `unknown` aren't played at launch

### 5.4 Pool balancing
When picking rounds for Classic/Daily:
- No two rounds from the same city in one game
- At most 2 rounds from the same country (when the World pool is used)
- Aim for a spread of price bands: pick from log-price quintiles, at least 3 different quintiles per game
- Never repeat a property for the same device within its last 20 games (soft; best-effort via device ID)
- **Country weighting for World games:** pick a country first (equal weight per country among those with ≥ 50 eligible properties), then a property within it. This way countries with huge open datasets (e.g., UK, France) don't dominate
- In single-country games the "≤ 2 per country" rule is ignored, but the city rule is kept where possible (relax it if the country has fewer than 5 cities in the pool)
- In default (Urban + Suburban) games, include at least 2 urban and 2 suburban rounds when the pool allows

### 5.5 Launch countries & currencies

| Country | ISO | Currency | In ECB/Frankfurter FX? | Candidate data sources (owner must verify license & robots.txt before enabling) | Notes |
|---|---|---|---|---|---|
| United States | US | USD | base currency | County/city open sales data (e.g., NYC Rolling Sales); licensed APIs; listing sites | Huge variety; weight by state so one city doesn't dominate |
| Canada | CA | CAD | yes | Listing sites; licensed APIs | No national open sales dataset |
| Mexico | MX | MXN | yes | Listing sites | Check Street View coverage, rural areas are patchy |
| Brazil | BR | BRL | yes | Listing sites | Many apartments, so check precision |
| Portugal | PT | EUR | yes | Listing sites | |
| Spain | ES | EUR | yes | Listing sites | |
| United Kingdom | GB | GBP | yes | HM Land Registry Price Paid (England & Wales, open data); listing sites | Scotland/NI need other sources |
| France | FR | EUR | yes | DVF / DVF géolocalisées (open government sales data with coordinates) | Excellent open data; filter to single-property sales |
| Italy | IT | EUR | yes | Listing sites | |
| Poland | PL | PLN | yes | Listing sites | |
| Croatia | HR | EUR | yes | Listing sites | Euro since 1 Jan 2023. Convert any older HRK prices at the fixed rate 7.53450 HRK = 1 EUR and store as EUR |
| South Africa | ZA | ZAR | yes | Listing sites | |
| Australia | AU | AUD | yes | NSW Valuer General bulk property sales data (open); listing sites | Other states vary |
| New Zealand | NZ | NZD | yes | Listing sites | |
| Japan | JP | JPY | yes | MLIT Real Estate Information Library transaction data (open API); listing sites | Government data is mostly district-level → `location_precision='district'`, which is not playable. Use it for validation/stats, or pair it with listing sources that have exact locations |
| Taiwan | TW | TWD | **no** | Ministry of the Interior actual price registration open data (實價登錄); listing sites | FX needs a fallback provider (6.5). Addresses are often given as ranges → usually `street` precision |

- Store this table as data in `backend/app/core/countries.py` (code, name, flag emoji, currency, region preset, default locale). Nothing else in the codebase should hard-code country lists.
- `GET /api/meta` returns each country with its eligible counts per setting, so the UI can disable empty options.
- **Launch target:** ≥ 200 eligible properties per country, with ≥ 50 urban and ≥ 50 suburban where possible. Countries below 50 eligible properties stay hidden until they have enough.

---

## 6. Systems

### 6.1 Sessions & anti-cheat (light touch)
- The client never receives the price before submitting a guess.
- `POST /api/games` creates a game server-side, picks the properties, and returns a `game_id` plus round 1 clues only.
- `POST /api/games/{game_id}/rounds/{n}/guess` scores the guess, returns the reveal data, and unlocks round n+1.
- The listing URL is only sent in the reveal response (it can contain the price).
- Rounds must be answered in order; a round can't be re-guessed.
- Leaderboard submissions are accepted only for completed games, using the server-computed score.
- Rate-limit game creation per IP (e.g., 30/hour) and guesses (e.g., 120/hour).

### 6.2 Device identity
- On first visit, generate a random UUID and keep it in localStorage (`ballpark_device_id`). Wrap localStorage reads and writes in try/catch.
- Send it as a header `X-Device-Id`. It's used only for daily-attempt limits and repeat avoidance. No accounts in MVP.

### 6.3 Daily challenge generation
- A scheduled job at 00:05 UTC creates `daily_challenges(date, property_ids[5])` using the pool rules plus a deterministic seed (`sha256(date + DAILY_SALT)`).
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
- Store metric. Display both: "120 m² (1,292 ft²)". 1 m² = 10.7639 ft².

---

## 7. Street View integration (Google Maps Platform)

### 7.1 Rules (must follow)
- Use the **Street View Static API** with our own API key and a **URL signing secret**.
- Images load **live** in the player's browser from Google's URL. The server never downloads, proxies, caches, or stores image bytes.
- Only `pano_id` may be stored long-term.
- Show Google's attribution and the "© Google" notice on/under the image, unaltered.
- Restrict the API key in Google Cloud Console to the Street View Static API only, and set a **daily quota cap** (config: `GOOGLE_DAILY_QUOTA`, default 300) to control cost. The free tier is 10,000 Static Street View requests/month; beyond that it's billed per 1,000.

### 7.2 Ingestion check (free metadata endpoint)
- For each new property, call `https://maps.googleapis.com/maps/api/streetview/metadata?location={lat},{lng}&radius=50&source=outdoor&key=…`
- If `status == "OK"`: store `pano_id`, set `sv_status = 'ok'`. Otherwise `sv_status = 'none'` (the property won't be played).
- Do NOT store the metadata's lat/lng or date.

### 7.3 Building the image URL at round time
1. Server calls the metadata endpoint again with `pano={pano_id}` to get the panorama's location (free, not stored).
2. Compute the **heading** from the panorama location to the property's lat/lng (initial bearing formula) so the camera faces the house.
3. Build the URL `https://maps.googleapis.com/maps/api/streetview?size=640x640&pano={pano_id}&heading={h}&pitch=5&fov=80&key={KEY}`, then sign it with the HMAC-SHA1 URL signing secret.
4. Return the signed URL in the round payload. The browser loads it directly.
5. Keep a server-side counter of URLs issued per UTC day. When `GOOGLE_DAILY_QUOTA` is reached, stop starting new games and show a friendly "We've hit today's limit — come back tomorrow (Daily Challenge still works)" message. The Daily Challenge gets a reserved budget (config `DAILY_RESERVED`, default 100).

### 7.4 Fallback
- If an image fails to load on the client, show a placeholder card ("No street image available") and let the player continue. Log it to `/api/telemetry/image-error` so the property can be marked `sv_status='none'`.

---

### 7.5 Image sources and order (owner change 2026-11-27)
At round time the server picks the first available image:
1. **Listing photo** (`image_url`): the source's own main photo, loaded by the browser straight
   from the source with the default referrer (no hotlink-protection workarounds; if the site
   blocks it, the client falls back). Credit: "Photo: {source name}"; the reveal links back.
2. **Google Street View**: only when `GOOGLE_MAPS_API_KEY` and the signing secret are set
   (§7.1–7.4 unchanged).
3. **Mapillary**: free, CC BY-SA 4.0 street-level photos. `ingest mapillary-check` stores the ID
   of a nearby non-panoramic image (≤ 60 m) whose camera faces the house. At round time the
   server resolves the current thumbnail URL via the Graph API (cached in memory for 1 h, never
   stored). Credit: "© Mapillary contributors · CC BY-SA 4.0". Token: `MAPILLARY_TOKEN`.
4. **Illustrated card** themed by setting and property type.

A client-side load failure reports `{game_id, round_no, source}`. The server then forgets only
that link (listing URL cleared until the next ingest, Google or Mapillary sent back for
re-checking). It never removes the home.

## 8. Data ingestion (scraper framework)

### 8.1 Architecture
```
backend/ingest/
  cli.py                 # `python -m ingest ...` entry point
  config.py              # loads sources.yaml + .env
  http.py                # PoliteClient (see 8.2)
  robots.py              # robots.txt checking + caching
  models.py              # NormalizedListing dataclass (matches 5.1)
  normalize.py           # parsing helpers: prices, areas, property types
  validate.py            # range checks, required fields, outliers
  fx.py                  # ECB/Frankfurter rate fetch + cache
  geocode.py             # Nominatim geocoder (polite, cached), used only if source lacks coords
  setting.py             # urban/suburban/rural classifier (Section 8.9)
  streetview.py          # metadata check → pano_id
  pipeline.py            # fetch → parse → normalize → validate → dedupe → upsert
  sources/
    base.py              # SourcePlugin abstract base class
    uk_price_paid.py     # HM Land Registry Price Paid CSV importer (open data)
    example_html.py      # reference plugin parsing tests/fixtures/example_listing.html
  sources.yaml           # enabled sources and per-source settings
```

### 8.2 PoliteClient requirements
- Honest User-Agent from config: `BallparkBot/1.0 (+https://<domain>/about; contact: <email>)`
- Checks robots.txt before every new path. If disallowed → skip and log. Cache robots.txt for 24 h.
- Per-domain minimum delay (default 5 s, configurable per source, never below 2 s), plus random jitter of 0–2 s
- Max 1 concurrent request per domain
- On-disk HTTP cache (e.g., `hishel` or a simple sqlite cache) so pages aren't refetched within `cache_ttl_hours` (default 72)
- Retries: max 2, exponential backoff, only on 5xx/timeouts
- **On 403, 429, or a detected challenge page** (Cloudflare/CAPTCHA markers in the body): stop that source's run immediately, log `BLOCKED`, and do not retry until the next scheduled run. No proxy rotation, no header spoofing, no headless-browser evasion.
- Never sends cookies or credentials. Logged-out only.

### 8.3 SourcePlugin interface
```python
class SourcePlugin(ABC):
    key: str                 # "uk_price_paid"
    display_name: str        # "HM Land Registry Price Paid Data"
    homepage: str
    price_type: Literal["sale_record", "asking"]
    country_codes: list[str]

    @abstractmethod
    def discover(self, client, settings) -> Iterable[str]:
        """Yield listing URLs or record IDs to fetch."""

    @abstractmethod
    def fetch_and_parse(self, client, ref) -> NormalizedListing | None:
        """Return a normalized record with FACT FIELDS ONLY, or None to skip."""
```
- Plugins must only return fields in `NormalizedListing`. There is no field for images, descriptions, or contact info, so they can't be stored by accident.
- `sources.yaml` example:
```yaml
uk_price_paid:
  enabled: true
  max_records_per_run: 2000
  filters: { min_year: 2022, property_types: [D, S, T, F] }
example_html:
  enabled: false
  delay_seconds: 5
  max_records_per_run: 50
```

### 8.4 UK Price Paid importer (first real data source)
- Downloads the yearly or monthly CSV from HM Land Registry (Open Government Licence; include the required attribution on the About page).
- Maps property type codes (D=detached house, S=semi-detached house, T=terraced/townhouse, F=flat/apartment). Skip `O` (other) and category B (non-standard) transactions.
- The CSV has addresses but not coordinates. Geocode the **full address** in memory (house number + street + town + postcode) with Nominatim, then store only lat/lng, city, and region. Never store the street address. Set `location_precision='exact'` when Nominatim returns a building/house-level match, `street` for a street match, and otherwise fall back to the postcode centroid via postcodes.io with `location_precision='district'` (not playable).
- Nominatim's public server allows at most 1 request/second, so limit batch sizes (e.g., 2,000 per run) or let the owner set `NOMINATIM_URL` to a self-hosted instance.
- Price is GBP; FX to USD at the transfer date.
- Random-sample to `max_records_per_run`, spread across regions.

### 8.5 Validation & cleaning
- Reject if: price_usd < 5,000 or > 100,000,000; area_m2 present and < 10 or > 50,000; price per m² < $50 or > $100,000 (likely bad parse)
- Dedupe key: `(source_id, source_ref)`; also flag possible cross-source duplicates when lat/lng within 15 m and price within 2%
- Normalize property types to the 5 allowed values

### 8.6 CLI commands
```
python -m ingest run --source uk_price_paid      # run one source
python -m ingest run --all                       # run all enabled sources
python -m ingest streetview-check --limit 500    # fill pano_id for unchecked records
python -m ingest fx-update                       # refresh FX cache
python -m ingest stats                           # counts by country/source/sv_status
python -m ingest deactivate --source example_html  # bulk-remove a source (takedown)
python -m ingest removals                        # list pending removal requests
python -m ingest remove --property-id <uuid>     # remove one record + add to blocklist
```

### 8.8 Country whitelist
- `pipeline.py` drops any record whose `country_code` isn't in `countries.py`, and logs the count per run.

### 8.9 Urban / suburban / rural classification
Use the **GHSL Degree of Urbanisation settlement model (GHS-SMOD)** from the European Commission JRC. It's a free global raster (CC BY 4.0) that labels every 1 km grid cell. Download the latest epoch once (owner runs `python -m ingest setting-data download`, or downloads it manually into `data/ghsl/`).

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
- Keep the dataset open once per ingest run. Sampling must be fast (thousands of points per second)
- **Adjustment rule:** an `apartment` in a code-30 cell stays urban. A `house` with area > 400 m² in a code-23 cell is reclassified to suburban (large detached houses inside dense clusters are usually edge-of-city). Keep this rule in one small function so the owner can tweak it
- CLI: `python -m ingest reclassify-settings` recomputes the setting for every property (e.g., after a new GHSL epoch or a rule change)
- If the GHSL file is missing, set `setting='unknown'` and log a warning instead of failing the run
- Add the GHSL citation to the About page

### 8.7 Scheduling
- A cron container or host cron: `ingest run --all` weekly (Sunday 03:00 UTC), `streetview-check` after it, `fx-update` daily, daily-challenge generation daily at 00:05 UTC.

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
  Makefile                 # dev, test, lint, build, up, down, migrate, seed
  .env.example
  docs/
    GDD.md                 # this file
    DECISIONS.md
    SOURCES.md             # how to add a new source plugin, with compliance checklist
  backend/
    pyproject.toml
    app/
      main.py
      api/ games.py, daily.py, leaderboards.py, removals.py, telemetry.py, health.py
      core/ config.py, db.py, security.py (rate limits), scoring.py, streetview_urls.py, selection.py
      models/ (SQLAlchemy models)
    ingest/  (see Section 8)
    alembic/
    tests/
  frontend/
    package.json
    src/
      main.tsx, App.tsx, api.ts, deviceId.ts, format.ts
      screens/ Home, Round, Reveal, Summary, Leaderboards, About
      components/ GuessInput, LogSlider, ClueChips, MiniMap, StreetViewImage, ShareButton
      styles/
    tests/
  deploy/
    docker-compose.yml
    Caddyfile
    backup.sh
```

### 9.3 Database tables
- `sources(id, key, display_name, homepage, license_note, enabled)`
- `properties(...)` — see 5.1
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
- `removal_requests(id, email, reference, message, status, created_at)`
- `blocklist(source_id, source_ref)` — never re-ingest these
- `sv_usage(date PK, urls_issued, daily_reserved_used)`

### 9.4 API (JSON, prefix `/api`)
| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /meta` | enabled sources, countries (from countries.py) with eligible counts per setting, region presets, daily number, quota status |
| `POST /games` `{mode, where_scope?, where_value?, difficulty?}` | create game → `{game_id, rounds_total, round: RoundPayload}`. Defaults: `where_scope=world`, `difficulty=normal`. `setting_filter` is derived from mode (`classic`/`daily` → `urban_suburban`). 422 if the pool has < 5 eligible properties for those settings |
| `POST /games/{id}/rounds/{n}/guess` `{amount, currency}` | → `{reveal: RevealPayload, next_round?: RoundPayload, summary?: SummaryPayload}`. **Server enforces the currency:** in Normal it must be `USD`, in Hard it must equal the property's local currency, otherwise 422 |
| `GET /daily` | today's status for this device (played? score? difficulty?) |
| `POST /daily/start` `{difficulty}` | like `POST /games` with mode=daily; 409 if already played today |
| `GET /leaderboards/{mode}?difficulty=&where_scope=&where_value=&period=day|week|all` | top 100 |
| `POST /leaderboards` `{game_id, nickname}` | submit a completed game |
| `POST /hl/next` / `POST /hl/answer` | Higher/Lower (Phase 4) |
| `POST /removals` | removal request |
| `POST /telemetry/image-error` `{game_id, round_no}` | flag a broken image |

`RoundPayload`: `{round_no, streetview_url, attribution, difficulty, guess_currency, slider: {min, max}, clues: {country, country_code, flag, region?, city, setting, property_type, area_m2?, bedrooms?, bathrooms?, year_built?, price_year, price_type}, map: {lat_approx, lng_approx}, local_currency}`

- `lat_approx/lng_approx` = coordinates rounded to 2 decimals (~1 km).
- `guess_currency` is `USD` in Normal and the local currency in Hard. The payload never includes an FX rate in Hard mode.

`RevealPayload`: `{price_local, currency, price_usd, guess_local, guess_usd, pct_off, score, label, price_per_m2_local?, price_date, source_name, listing_url?, fx_hint?}`

- `fx_hint` (e.g., `"1 USD ≈ 151 JPY"`) is included in every reveal and shown prominently in Hard mode.

### 9.5 Configuration (.env)
```
DATABASE_URL=sqlite:///./data/ballpark.db
GOOGLE_MAPS_API_KEY=
GOOGLE_URL_SIGNING_SECRET=
GOOGLE_DAILY_QUOTA=300
DAILY_RESERVED=100
DAILY_SALT=change-me
LAUNCH_DATE=2027-01-01
PUBLIC_BASE_URL=https://ballpark.example.com
CONTACT_EMAIL=you@example.com
SCRAPER_USER_AGENT=BallparkBot/1.0 (+https://ballpark.example.com/about; contact: you@example.com)
ADMIN_TOKEN=change-me            # protects nothing public; reserved for future admin endpoints
CORS_ORIGINS=http://localhost:5173
MAX_PRICE_AGE_YEARS=5
MIN_POOL_PER_OPTION=50
NOMINATIM_URL=https://nominatim.openstreetmap.org
GHSL_SMOD_PATH=./data/ghsl/GHS_SMOD.tif
FX_MANUAL_CSV=./data/fx_manual.csv
```

---

## 10. Self-hosting & deployment

### 10.1 docker compose services
- `api`: FastAPI app (Uvicorn, 2 workers), mounts `./data` for SQLite
- `web`: built frontend served as static files by Caddy
- `caddy`: reverse proxy; `/api/*` → api, everything else → static frontend; automatic HTTPS for the configured domain
- `cron`: lightweight container running the schedule in 8.7 (supercronic or a simple loop)

### 10.2 Hosting options (document all in README)
- Any small VPS (1 vCPU / 1–2 GB RAM is plenty): Hetzner, DigitalOcean, Linode, Oracle free tier
- Or a home server / Raspberry Pi 4/5 with Cloudflare Tunnel or port forwarding
- Domain pointed at the server; Caddy handles certificates

### 10.3 Ops
- `deploy/backup.sh`: nightly SQLite backup using `sqlite3 .backup`, keeps 14 days
- Logs to stdout (docker logs); ingest runs also write a summary row to a `ingest_runs` table
- `make up`, `make down`, `make logs`, `make migrate`, `make seed`

### 10.4 Local development
- `make dev` runs the API on :8000 with reload and Vite on :5173 with a proxy to the API
- `make seed` loads ~50 fixture properties (fake, clearly labeled "DEMO") so the game is playable without any scraping or Google key. In dev without a Google key, show a placeholder image.

---

## 11. Performance, privacy & security
- Round creation < 300 ms server time (excluding Google metadata call); cache the metadata panorama location in memory for 10 minutes only (not persisted)
- Frontend bundle < 250 KB gzipped (excluding map tiles)
- No third-party analytics in MVP. If added later, use a privacy-friendly self-hosted option
- Collect no personal data except: device UUID, optional nickname, removal-request email
- Security headers via Caddy (CSP allowing `https:` images, since listing photos are hotlinked from their sources, HSTS, X-Content-Type-Options)
- Input validation with Pydantic on every endpoint; parameterized queries only
- OSM tiles: follow the OpenStreetMap tile usage policy (attribution, valid referrer, low volume). Make the tile URL configurable so a different tile provider can be swapped in if traffic grows

---

## 12. Compliance rules (hard requirements)

1. **Facts plus a linked photo.** Never store descriptions or personal/contact data (enforced by
   the `NormalizedListing` schema). *(Changed by the owner, 2026-11-27.)* A source's main listing
   photo **may be shown**, but only as a URL on the source that the player's browser loads
   directly. We never download, proxy, cache, crop or re-host image files, the photo is always
   credited to its source with a link back, and any source's photos can be switched off
   (`photos: false` in sources.yaml) and purged (`ingest strip-photos --source KEY`) at once on
   request. The owner accepts the copyright risk of showing third-party listing photos and
   should revisit it before any monetization (rule 8).
2. **No Google content storage** except `pano_id`. No proxying or caching Street View images. Signed URLs only. Attribution visible. **Mapillary**: store only the image ID, show the CC BY-SA attribution with every image.
3. **No Google geocoding.** Coordinates come from the source, postcodes.io, or Nominatim (max 1 req/s, cached, with a proper User-Agent).
4. **Polite scraping:** robots.txt respected, per-domain delays, honest User-Agent, logged out, caching, and stop on block. **No circumvention of any kind.**
5. **Link back** to the original listing on the reveal screen when a URL exists, and credit the source.
6. **Removal path:** public removal form, CLI to remove a record or a whole source, and a blocklist so removed items never return. Target: act within 72 hours.
7. **Open data licenses:** show the required attribution for each open dataset on the About page (e.g., "Contains HM Land Registry data © Crown copyright and database right [year]. This data is licensed under the Open Government Licence v3.0.").
8. **Non-commercial at launch:** no ads or payments. If monetization is added later, revisit every source's terms first.
9. `docs/SOURCES.md` must contain a checklist that every new source plugin has to pass: robots.txt allows the paths, logged-out access, no PII fields, photos as URLs only (or `photos: false`), delay ≥ 2 s, attribution added, link-back implemented.

---

## 13. Testing & acceptance

### 13.1 Backend unit tests
- Scoring: exact guess = 5000; 2× high and 2× low give equal scores; ≥3× = 0; currency conversion before scoring; a Normal USD guess and the equivalent Hard local guess score the same
- Countries: every entry in countries.py has a valid ISO code, currency, region preset, and flag; records from other countries are dropped
- FX: TWD uses the fallback provider; HRK prices before 2023 convert to EUR at 7.53450
- Setting classifier: known lat/lng points (use a tiny synthetic test raster, not the real GHSL file) map to the right setting; the adjustment rule works; a missing raster gives `unknown` without crashing
- Hard-mode slider bounds round to nice numbers for JPY, TWD, ZAR, PLN, and EUR
- Selection: no repeated city, ≤ 2 per country, price-band spread, eligibility filters
- Heading calculation against known coordinate pairs
- URL signing matches Google's documented example
- PoliteClient: obeys robots.txt (use a local test server), enforces delay, stops on 403/429/challenge markers
- Normalizers: price strings in many formats ("€ 340.000", "$1.2M", "£425,000", "¥38,000,000"), area units (m², ft², sqm)
- Validation rejects outliers
- UK Price Paid importer parses a fixture CSV correctly

### 13.2 API tests
- Price is never present in a RoundPayload; listing_url only appears in reveals
- Hard mode: RoundPayload has no USD values or FX rate; a guess in the wrong currency → 422
- Urban/Suburban games only contain properties with the matching setting; default games contain only urban and suburban (never rural/unknown)
- `POST /games` with no difficulty or where_scope → a Normal (USD), World game
- Leaderboards never mix difficulties or "Where" settings
- Can't guess the same round twice or skip ahead
- Daily: second attempt from the same device → 409
- Leaderboard rejects incomplete games and uses the server score
- Quota: when the Google counter hits the limit, `POST /games` returns 503 with a friendly code while Daily still works within its reserve

### 13.3 Frontend tests
- GuessInput formats numbers, the slider and text stay in sync, and the log mapping round-trips
- The Normal/Hard toggle changes the input currency and slider range; Hard shows no USD anywhere on the round screen
- The country dropdown is grouped by region, and options with too few properties are disabled
- The full game flow renders with a mocked API

### 13.4 End-to-end smoke test (Playwright)
- With seed data: start Classic → 5 guesses → summary shows 5 rows and a total → share text copied

---

## 14. Build phases & milestones

### Phase 1 — Playable skeleton (seed data, no scraping)
- Repo layout, Makefile, docker compose, Caddy config
- DB models + migrations, seed script with 50 DEMO properties
- `countries.py` with all 16 launch countries; seed data spread across all 16 (≥ 3 each, with a mix of urban/suburban/rural and both currencies' formats)
- Scoring, selection, the games API (Classic), **Normal and Hard difficulty**
- Frontend: Home (with Where + Difficulty settings), Round, Reveal, Summary screens; GuessInput with log slider; placeholder image
- **Done when:** `make dev` lets you play a full 5-round Classic game in both Normal and Hard, on desktop and mobile widths, and all tests pass

### Phase 2 — Real data pipeline
- Ingest framework, PoliteClient, robots.txt, FX (including the TWD fallback and HRK conversion), validation, country whitelist, CLI
- GHSL setting classifier + `reclassify-settings` command
- UK Price Paid importer + Nominatim/postcodes.io geocoding with location_precision
- `example_html` reference plugin against a fixture file
- `docs/SOURCES.md` with the compliance checklist and a "how to write a plugin" guide
- **Done when:** `ingest run --source uk_price_paid` loads ≥ 1,000 valid records, and `ingest stats` shows them

### Phase 3 — Street View + Daily
- Street View metadata check, signed URL generation with heading, quota counter, attribution, image-error telemetry
- Mini map with OSM tiles
- Daily Challenge (Normal + Hard), share text with 🔥 HARD tag, leaderboards with mode/difficulty/where filters, nickname filter
- **Urban and Suburban modes** on Home, with their own leaderboards
- About / Data & Removal page + removal form + CLI removal commands
- **Done when:** a Daily Challenge with real Street View images is playable end to end, and the quota limit behaves as specified

### Phase 4 — More modes & polish
- Regional mode (region presets + single country), Higher/Lower mode (Normal + Hard)
- Animations, dark mode, accessibility pass (keyboard-only playthrough, screen-reader labels)
- Repeat-avoidance per device
- Backups, cron container, README deployment guide for VPS and home server
- **Done when:** deployed on a real domain over HTTPS with backups running

### Phase 5 — Owner-driven source expansion (ongoing)
- The owner adds one new source plugin at a time, following SOURCES.md. Claude Code helps write each plugin only after the owner confirms the site and the checklist.
- Suggested order: France (DVF, open data) → Australia (NSW open data) → Taiwan (open data) → US open city/county data → listing-site plugins for the remaining countries
- Track progress against the launch target in 5.5 with `ingest stats --by country,setting`

---

## 15. Open questions for the owner (answer before Phase 3)
1. Final game name and domain?
2. Accent color / visual vibe preference?
3. Should the Daily Challenge use only `sale_record` data (more "real") or mix in asking prices?
4. Any interest in a timer option, or an "extra hard" mode that also hides clues like size and bedrooms?
5. Should rural properties be added later, as their own mode or as an "include rural" option?
