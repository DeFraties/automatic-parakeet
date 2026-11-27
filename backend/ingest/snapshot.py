"""Export / load a source's imported properties as a portable snapshot file.

Lets one machine do the slow work (downloads, geocoding at 1 request/second, GHSL
classification) and another load the result in seconds:

    python -m ingest snapshot export uk_price_paid data/snapshots/uk_price_paid.jsonl.gz
    python -m ingest snapshot load data/snapshots/uk_price_paid.jsonl.gz

Only the fields of `properties` are exported (facts, coordinates, setting, image IDs/URLs).
Loading never re-activates a deactivated home and skips blocklisted records.
"""

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Blocklist, Property, Source, utcnow

FORMAT_VERSION = 1

FIELDS = (
    "source_ref", "listing_url", "image_url", "price_type", "price_local", "currency",
    "price_usd", "fx_rate_to_usd", "price_date", "country_code", "region", "city", "lat", "lng",
    "location_precision", "setting", "setting_class_raw", "property_type", "area_m2",
    "bedrooms", "bathrooms", "year_built", "pano_id", "sv_status", "mly_image_id", "mly_status",
)  # fmt: skip


def export(
    db: Session,
    source_key: str,
    path: str | Path,
    notice: str = "",
    playable_only: bool = False,
) -> int:
    """playable_only: skip district-precision records (never playable, so no need to ship)."""
    src = db.execute(select(Source).where(Source.key == source_key)).scalar_one_or_none()
    if src is None:
        raise ValueError(f"unknown source {source_key!r}")
    q = select(Property).where(Property.source_id == src.id, Property.is_active.is_(True))
    if playable_only:
        q = q.where(Property.location_precision.in_(("exact", "street")))
    rows = db.execute(q.order_by(Property.source_ref)).scalars()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        header = {
            "format": FORMAT_VERSION,
            "source": {
                "key": src.key,
                "display_name": src.display_name,
                "homepage": src.homepage,
                "license_note": src.license_note,
            },
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "notice": notice,
        }
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for p in rows:
            rec = {f: getattr(p, f) for f in FIELDS}
            rec["price_date"] = p.price_date.isoformat()
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def load(db: Session, path: str | Path) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "skipped_blocklisted": 0, "skipped_inactive": 0}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        header = json.loads(fh.readline())
        if header.get("format") != FORMAT_VERSION:
            raise ValueError(f"unsupported snapshot format {header.get('format')!r}")
        meta = header["source"]
        src = db.execute(select(Source).where(Source.key == meta["key"])).scalar_one_or_none()
        if src is None:
            src = Source(key=meta["key"], enabled=True)
            db.add(src)
        src.display_name = meta["display_name"]
        src.homepage = meta.get("homepage")
        src.license_note = meta.get("license_note")
        db.flush()
        blocked = set(
            db.execute(select(Blocklist.source_ref).where(Blocklist.source_id == src.id)).scalars()
        )
        existing = {
            p.source_ref: p
            for p in db.execute(select(Property).where(Property.source_id == src.id)).scalars()
        }
        for i, line in enumerate(fh):
            rec = json.loads(line)
            ref = rec["source_ref"]
            if ref in blocked:
                counts["skipped_blocklisted"] += 1
                continue
            prop = existing.get(ref)
            if prop is not None and not prop.is_active:
                counts["skipped_inactive"] += 1  # removed on this machine: keep it removed
                continue
            if prop is None:
                prop = Property(source_id=src.id, source_ref=ref, is_active=True)
                db.add(prop)
                counts["inserted"] += 1
            else:
                counts["updated"] += 1
            for f in FIELDS:
                setattr(prop, f, rec.get(f))
            prop.price_date = date.fromisoformat(rec["price_date"])
            prop.sv_status = rec.get("sv_status") or "unchecked"
            prop.mly_status = rec.get("mly_status") or "unchecked"
            prop.updated_at = utcnow()
            if i % 500 == 499:
                db.flush()
    db.commit()
    return counts
