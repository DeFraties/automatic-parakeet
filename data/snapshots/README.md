# Data snapshots

Pre-built imports that load in seconds with `make load-uk`, so a new machine doesn't have to
repeat the slow import (downloads plus geocoding at 1 request/second).

## `uk_price_paid.jsonl.gz`

1,283 recorded house sales in England & Wales (2022 onwards), each located to the building or
street. Fields: price, date, property type, town, county, coordinates, urban/suburban/rural
setting and a link to the Land Registry record. **No street addresses, postcodes or names.**
(Postcode-level records were left out: they're never playable.)

Licences and required attribution:

- Contains HM Land Registry data © Crown copyright and database right 2026. This data is
  licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
- Coordinates derived from OpenStreetMap data via Nominatim, © OpenStreetMap contributors,
  available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/),
  and from postcodes.io: contains OS data © Crown copyright and database right; contains Royal
  Mail data © Royal Mail copyright and database right; contains National Statistics data ©
  Crown copyright and database right.
- Urban/suburban/rural setting from GHSL GHS-SMOD R2023A, European Commission, Joint Research
  Centre, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Because the coordinates derive from OpenStreetMap, this file as a database is shared under
ODbL 1.0 terms.

Removal: if a home here is yours, use the removal form on the game's About page. Removed homes
are blocklisted and skipped when a snapshot is loaded.

## Making a new snapshot

```bash
backend/.venv/bin/python -m ingest snapshot export uk_price_paid data/snapshots/uk_price_paid.jsonl.gz --playable-only
```
