"""Load 51 fictional DEMO properties so the game is playable with no scraping.

Run with `make seed` (or `python -m app.seed` from the repo root). Idempotent: re-running updates
the same records. Every record belongs to the "demo" source and is clearly labeled as DEMO data.
Prices, sizes and dates are invented; coordinates are only approximate city/neighborhood points.
Photos are original placeholder illustrations in frontend/public/demo-photos/ (never real
listing photos), served by our own site.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.countries import COUNTRIES_BY_CODE
from app.core.db import SessionLocal
from app.models import FxRate, Property, PropertyImage, Source, utcnow

DEMO_SOURCE_KEY = "demo"
FX_DATE = date(2020, 1, 1)

# Fixed demo FX rates: USD per 1 unit of currency. Real rates come from ECB/Frankfurter (Phase 2).
DEMO_FX: dict[str, float] = {
    "USD": 1.0,
    "CAD": 0.72,
    "MXN": 0.055,
    "BRL": 0.18,
    "EUR": 1.08,
    "GBP": 1.27,
    "PLN": 0.25,
    "ZAR": 0.054,
    "AUD": 0.66,
    "NZD": 0.60,
    "JPY": 0.0067,
    "TWD": 0.031,
}

S, A = "sale_record", "asking"

# (country, city, region, lat, lng, setting, type, area_m2, beds, baths, year_built, price, type)
DEMO_PROPERTIES = [
    (
        "US",
        "New York",
        "New York",
        40.6782,
        -73.9442,
        "urban",
        "apartment",
        85,
        2,
        1,
        1931,
        1_150_000,
        A,
    ),
    ("US", "Austin", "Texas", 30.4015, -97.7525, "urban", "house", 210, 4, 3, 2004, 615_000, S),
    ("US", "Millersburg", "Ohio", 40.5545, -81.9179, "rural", "house", 160, 3, 2, 1925, 289_000, A),
    ("US", "Mesa", "Arizona", 33.4152, -111.8315, "urban", "house", 150, 3, 2, 1998, 445_000, S),
    (
        "CA",
        "Toronto",
        "Ontario",
        43.6532,
        -79.3832,
        "urban",
        "apartment",
        70,
        2,
        2,
        2012,
        865_000,
        A,
    ),
    (
        "CA",
        "Calgary",
        "Alberta",
        51.1215,
        -114.0076,
        "urban",
        "house",
        190,
        4,
        3,
        2008,
        720_000,
        A,
    ),
    (
        "CA",
        "Lunenburg",
        "Nova Scotia",
        44.3770,
        -64.3091,
        "rural",
        "house",
        140,
        3,
        1,
        1890,
        385_000,
        A,
    ),
    (
        "MX",
        "Mexico City",
        "CDMX",
        19.4194,
        -99.1617,
        "urban",
        "apartment",
        95,
        2,
        2,
        1950,
        7_800_000,
        A,
    ),
    (
        "MX",
        "Zapopan",
        "Jalisco",
        20.7214,
        -103.3918,
        "urban",
        "house",
        220,
        3,
        3,
        2010,
        5_400_000,
        A,
    ),
    (
        "MX",
        "Mérida",
        "Yucatán",
        21.0400,
        -89.6000,
        "urban",
        "house",
        180,
        3,
        2,
        2018,
        3_200_000,
        A,
    ),
    (
        "BR",
        "São Paulo",
        "São Paulo",
        -23.5614,
        -46.6559,
        "urban",
        "apartment",
        78,
        2,
        2,
        1985,
        1_050_000,
        A,
    ),
    (
        "BR",
        "Curitiba",
        "Paraná",
        -25.4700,
        -49.2900,
        "urban",
        "house",
        160,
        3,
        2,
        2001,
        890_000,
        A,
    ),
    (
        "BR",
        "Tiradentes",
        "Minas Gerais",
        -21.1100,
        -44.1780,
        "rural",
        "house",
        120,
        2,
        1,
        1960,
        420_000,
        A,
    ),
    ("PT", "Lisbon", "Lisboa", 38.7139, -9.1394, "urban", "apartment", 65, 2, 1, 1940, 520_000, A),
    ("PT", "Maia", "Porto", 41.2357, -8.6199, "urban", "house", 180, 4, 3, 2005, 395_000, A),
    ("PT", "Arraiolos", "Évora", 38.7239, -7.9886, "rural", "house", 130, 3, 1, 1900, 145_000, A),
    (
        "ES",
        "Madrid",
        "Comunidad de Madrid",
        40.4300,
        -3.6800,
        "urban",
        "apartment",
        90,
        3,
        2,
        1970,
        640_000,
        A,
    ),
    (
        "ES",
        "Paterna",
        "Valencia",
        39.5030,
        -0.4400,
        "urban",
        "townhouse",
        160,
        4,
        3,
        2003,
        310_000,
        A,
    ),
    (
        "ES",
        "Seville",
        "Andalucía",
        37.3891,
        -5.9845,
        "urban",
        "apartment",
        75,
        2,
        1,
        1965,
        235_000,
        A,
    ),
    (
        "GB",
        "London",
        "Greater London",
        51.5450,
        -0.0550,
        "urban",
        "apartment",
        60,
        1,
        1,
        1900,
        585_000,
        S,
    ),
    (
        "GB",
        "Manchester",
        "Greater Manchester",
        53.4160,
        -2.2310,
        "urban",
        "house",
        110,
        3,
        1,
        1930,
        425_000,
        S,
    ),
    ("GB", "St Just", "Cornwall", 50.1240, -5.6800, "rural", "house", 85, 2, 1, None, 310_000, S),
    (
        "GB",
        "Leeds",
        "West Yorkshire",
        53.8300,
        -1.5800,
        "urban",
        "townhouse",
        90,
        3,
        1,
        1905,
        215_000,
        S,
    ),
    (
        "FR",
        "Paris",
        "Île-de-France",
        48.8650,
        2.3800,
        "urban",
        "apartment",
        48,
        1,
        1,
        1880,
        510_000,
        S,
    ),
    (
        "FR",
        "Écully",
        "Auvergne-Rhône-Alpes",
        45.7745,
        4.7775,
        "urban",
        "house",
        150,
        4,
        2,
        1975,
        720_000,
        S,
    ),
    (
        "FR",
        "Sarlat-la-Canéda",
        "Nouvelle-Aquitaine",
        44.8890,
        1.2160,
        "rural",
        "house",
        170,
        4,
        2,
        None,
        265_000,
        S,
    ),
    ("IT", "Milan", "Lombardy", 45.4642, 9.1900, "urban", "apartment", 80, 2, 1, 1960, 610_000, A),
    (
        "IT",
        "Casalecchio di Reno",
        "Emilia-Romagna",
        44.4800,
        11.2750,
        "urban",
        "house",
        140,
        3,
        2,
        1990,
        420_000,
        A,
    ),
    ("IT", "Mussomeli", "Sicily", 37.5790, 13.7520, "rural", "house", 100, 3, 1, 1920, 28_000, A),
    (
        "PL",
        "Warsaw",
        "Masovian",
        52.2297,
        21.0122,
        "urban",
        "apartment",
        55,
        2,
        1,
        2015,
        890_000,
        A,
    ),
    (
        "PL",
        "Wieliczka",
        "Lesser Poland",
        49.9870,
        20.0650,
        "urban",
        "house",
        160,
        4,
        2,
        2012,
        1_150_000,
        A,
    ),
    ("PL", "Hajnówka", "Podlaskie", 52.7430, 23.5810, "rural", "house", 90, 3, 1, 1965, 185_000, A),
    (
        "HR",
        "Zagreb",
        "City of Zagreb",
        45.8150,
        15.9819,
        "urban",
        "apartment",
        70,
        2,
        1,
        1975,
        245_000,
        A,
    ),
    (
        "HR",
        "Kaštela",
        "Split-Dalmatia",
        43.5500,
        16.3500,
        "urban",
        "house",
        180,
        4,
        3,
        2008,
        520_000,
        A,
    ),
    (
        "HR",
        "Đakovo",
        "Osijek-Baranja",
        45.3090,
        18.4100,
        "rural",
        "house",
        120,
        3,
        1,
        1970,
        48_000,
        A,
    ),
    (
        "ZA",
        "Cape Town",
        "Western Cape",
        -33.9150,
        18.3900,
        "urban",
        "apartment",
        85,
        2,
        2,
        1990,
        3_950_000,
        A,
    ),
    (
        "ZA",
        "Randburg",
        "Gauteng",
        -26.0940,
        28.0010,
        "urban",
        "house",
        280,
        4,
        3,
        1985,
        2_650_000,
        A,
    ),
    (
        "ZA",
        "Umhlanga",
        "KwaZulu-Natal",
        -29.7270,
        31.0850,
        "urban",
        "townhouse",
        150,
        3,
        2,
        2006,
        2_900_000,
        A,
    ),
    (
        "AU",
        "Sydney",
        "New South Wales",
        -33.8860,
        151.2110,
        "urban",
        "townhouse",
        110,
        3,
        2,
        1890,
        2_150_000,
        S,
    ),
    (
        "AU",
        "Box Hill",
        "Victoria",
        -37.8190,
        145.1220,
        "urban",
        "house",
        220,
        4,
        2,
        1965,
        1_480_000,
        S,
    ),
    (
        "AU",
        "Gulgong",
        "New South Wales",
        -32.3630,
        149.5330,
        "rural",
        "house",
        140,
        3,
        1,
        1920,
        420_000,
        S,
    ),
    (
        "NZ",
        "Auckland",
        "Auckland",
        -36.8485,
        174.7633,
        "urban",
        "apartment",
        75,
        2,
        1,
        2005,
        720_000,
        A,
    ),
    (
        "NZ",
        "Christchurch",
        "Canterbury",
        -43.5100,
        172.6000,
        "urban",
        "house",
        160,
        4,
        2,
        1995,
        690_000,
        A,
    ),
    (
        "NZ",
        "Lower Hutt",
        "Wellington",
        -41.2100,
        174.9080,
        "urban",
        "house",
        130,
        3,
        1,
        1955,
        740_000,
        A,
    ),
    (
        "JP",
        "Tokyo",
        "Tokyo",
        35.6620,
        139.7040,
        "urban",
        "apartment",
        55,
        2,
        1,
        2001,
        68_000_000,
        S,
    ),
    (
        "JP",
        "Toyonaka",
        "Osaka",
        34.7810,
        135.4700,
        "urban",
        "house",
        110,
        4,
        2,
        1998,
        42_000_000,
        S,
    ),
    ("JP", "Ōmachi", "Nagano", 36.5030, 137.8510, "rural", "house", 140, 5, 1, 1970, 8_500_000, A),
    (
        "JP",
        "Fukuoka",
        "Fukuoka",
        33.5900,
        130.4017,
        "urban",
        "apartment",
        70,
        3,
        1,
        2012,
        29_800_000,
        A,
    ),
    (
        "TW",
        "Taipei",
        "Taipei",
        25.0330,
        121.5654,
        "urban",
        "apartment",
        80,
        3,
        2,
        1990,
        32_000_000,
        S,
    ),
    (
        "TW",
        "Taichung",
        "Taichung",
        24.1800,
        120.6400,
        "urban",
        "townhouse",
        165,
        4,
        3,
        2008,
        18_500_000,
        S,
    ),
    (
        "TW",
        "Kaohsiung",
        "Kaohsiung",
        22.6273,
        120.3014,
        "urban",
        "apartment",
        95,
        3,
        2,
        2000,
        11_800_000,
        S,
    ),
]

DEMO_PHOTO_BASE = "/demo-photos/"
ROOMS = ("room-living.svg", "room-kitchen.svg", "room-bedroom.svg")


def demo_photos(i: int, ptype: str, setting: str) -> list[tuple[str, str | None]]:
    """(filename, kind) for a demo home: a matching exterior, 2-3 rooms, sometimes a floor plan."""
    if ptype == "apartment":
        lead = "apartment-tower.svg" if i % 2 else "apartment-block.svg"
    elif ptype == "townhouse":
        lead = "townhouse-row.svg"
    elif ptype == "land":
        lead = "plot-land.svg"
    elif setting == "rural":
        lead = "house-rural.svg"
    else:
        lead = "villa.svg" if i % 5 == 0 else "house-suburban.svg"
    rooms = [ROOMS[(i + k) % 3] for k in range(2 + i % 2)]
    photos = [(lead, "photo")] + [(r, "photo") for r in rooms]
    if i % 3 == 0:
        photos.append(("floorplan.svg", "floorplan"))
    return photos


_NS = uuid.UUID("6b3f0d1e-5a1c-4d55-9a8e-6f2b8f1c0b11")


def seed(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    src = db.execute(select(Source).where(Source.key == DEMO_SOURCE_KEY)).scalar_one_or_none()
    if src is None:
        src = Source(key=DEMO_SOURCE_KEY)
        db.add(src)
    src.display_name = "DEMO data (fictional)"
    src.homepage = None
    src.license_note = "Invented sample data for development. Not real sales or listings."
    src.image_hosts = []  # demo photos are served by our own site
    src.enabled = True
    db.flush()

    for cur, rate in DEMO_FX.items():
        db.merge(FxRate(date=FX_DATE, currency=cur, rate_to_usd=rate))

    for i, row in enumerate(DEMO_PROPERTIES):
        cc, city, region, lat, lng, setting, ptype, area, beds, baths, year, price, ptype2 = row
        currency = COUNTRIES_BY_CODE[cc].currency
        rate = DEMO_FX[currency]
        ref = f"demo-{i + 1:03d}"
        pid = str(uuid.uuid5(_NS, ref))
        p = db.get(Property, pid) or Property(id=pid, source_id=src.id, source_ref=ref)
        p.listing_url = f"https://example.com/demo/{ref}"  # every playable home links back
        p.price_type = ptype2
        p.price_local = price
        p.currency = currency
        p.fx_rate_to_usd = rate
        p.price_usd = round(price * rate, 2)
        p.price_date = today - timedelta(days=(i * 53) % 600 + 10)  # within MAX_PRICE_AGE_YEARS
        p.country_code = cc
        p.region = region
        p.city = city
        p.lat, p.lng = lat, lng
        p.location_precision = "exact"
        p.setting = setting
        p.property_type = ptype
        p.area_m2 = area
        p.bedrooms, p.bathrooms, p.year_built = beds, baths, year
        p.is_active = True
        if p.images:  # re-seed: delete old photo rows before inserting the same positions
            p.images.clear()
            db.flush()
        p.images = [
            PropertyImage(position=pos, url=DEMO_PHOTO_BASE + name, width=1200, height=800,
                          kind=kind, status="ok")
            for pos, (name, kind) in enumerate(demo_photos(i, ptype, setting))
        ]  # fmt: skip
        p.images_status = "ok"
        p.images_checked_at = utcnow()
        p.last_seen_at = utcnow()
        db.add(p)
    db.commit()
    return len(DEMO_PROPERTIES)


def main() -> None:
    with SessionLocal() as db:
        n = seed(db)
    print(f"Seeded {n} DEMO properties.")


if __name__ == "__main__":
    main()
