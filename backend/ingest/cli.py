"""`python -m ingest ...` — run from the repo root (so `.env` and `./data` resolve).

Phase 2 commands:
  run --source KEY | --all [--limit N]   run one / all enabled sources
  fx-update [--days N]                   refresh FX cache (ECB + manual fallback CSV)
  stats [--by country,setting]           counts by country / source / sv_status (or custom)
  reclassify-settings                    recompute urban/suburban/rural for every property
  setting-data download                  download the GHSL GHS-SMOD raster
  streetview-check [--limit N]           fill pano_id / sv_status for unchecked records
  mapillary-check [--limit N]            find a Mapillary photo for unchecked records
  strip-photos --source KEY              forget a source's listing photo URLs (photo takedown)
  snapshot export KEY FILE | load FILE   move imported data between machines
  deactivate --source KEY                bulk-remove a source (takedown)
  removals                               list pending removal requests
  remove --property-id UUID [--request N] remove one record + blocklist it
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.models import Blocklist, IngestRun, Property, RemovalRequest, Source
from ingest.cache import SqliteCache
from ingest.config import load_sources, settings
from ingest.fx import FxService, ManualCsvFxProvider
from ingest.geocode import Geocoder
from ingest.http import PoliteClient
from ingest.pipeline import IngestDeps, run_source
from ingest.setting import SettingClassifier
from ingest.sources import PLUGINS
from ingest.sources.base import PluginContext

log = logging.getLogger("ingest")

STATS_COLUMNS = {
    "country": Property.country_code,
    "source": Source.key,
    "sv_status": Property.sv_status,
    "setting": Property.setting,
    "precision": Property.location_precision,
    "type": Property.property_type,
    "price_type": Property.price_type,
}


def _fx(db: Session) -> FxService:
    s = settings()
    return FxService(
        db,
        api_url=s.fx_api_url,
        user_agent=s.scraper_user_agent,
        fallback=ManualCsvFxProvider(s.fx_manual_csv),
    )


def cmd_run(args) -> int:
    s = settings()
    sources = load_sources(args.config)
    if args.all:
        keys = [k for k, c in sources.items() if c.enabled]
    elif args.source:
        if args.source not in PLUGINS:
            print(f"Unknown source {args.source!r}. Known: {', '.join(PLUGINS)}", file=sys.stderr)
            return 2
        keys = [args.source]
    else:
        print("Pass --source KEY or --all", file=sys.stderr)
        return 2

    status = 0
    cache_dir = Path(s.ingest_cache_dir)
    for key in keys:
        cfg = sources.get(key)
        if cfg is None:
            print(f"{key}: not configured in sources.yaml", file=sys.stderr)
            status = 2
            continue
        if not cfg.enabled and not args.source:
            continue
        client = PoliteClient(
            s.scraper_user_agent,
            cache_dir,
            default_delay=cfg.delay_seconds,
            cache_ttl_hours=cfg.cache_ttl_hours,
        )
        geo_cache = SqliteCache(cache_dir / "geocode_cache.sqlite")
        geocoder = Geocoder(
            user_agent=s.scraper_user_agent,
            nominatim_url=s.nominatim_url,
            postcodes_url=s.postcodes_io_url,
            cache=geo_cache,
        )
        with SessionLocal() as db, SettingClassifier(s.ghsl_smod_path) as classifier:
            fx = _fx(db)
            plugin = PLUGINS[key](PluginContext(geocoder=geocoder, cache_dir=str(cache_dir)))
            try:
                run = run_source(
                    db, plugin, cfg, IngestDeps(client, fx, classifier), limit=args.limit
                )
            finally:
                fx.close()
                geocoder.close()
                geo_cache.close()
                client.close()
            print(
                f"{key}: {run.status} — inserted {run.inserted}, updated {run.updated}, "
                f"rejected {run.rejected}, skipped {run.skipped}, "
                f"dropped (country) {run.dropped_country}, "
                f"possible duplicates {run.possible_duplicates}"
            )
            if run.message:
                print(f"  {run.message}")
            if run.status != "ok":
                status = 1
    return status


def cmd_fx_update(args) -> int:
    with SessionLocal() as db:
        fx = _fx(db)
        try:
            n = fx.update(days=args.days)
        finally:
            fx.close()
    print(f"Stored {n} FX rates.")
    return 0


def _table(rows: list[tuple], headers: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows, strict=False)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(str(v).ljust(w) for v, w in zip(r, widths, strict=True)) for r in rows]
    return "\n".join(out)


def stats_rows(db: Session, by: list[str]) -> list[tuple]:
    cols = [STATS_COLUMNS[b] for b in by]
    q = (
        select(*cols, func.count())
        .select_from(Property)
        .join(Source, Source.id == Property.source_id)
        .group_by(*cols)
        .order_by(*cols)
    )
    return [tuple(r) for r in db.execute(q).all()]


def cmd_stats(args) -> int:
    groupings = [args.by.split(",")] if args.by else [["source"], ["country"], ["sv_status"]]
    for g in groupings:
        bad = [b for b in g if b not in STATS_COLUMNS]
        if bad:
            print(f"Unknown --by field(s): {bad}. Use: {', '.join(STATS_COLUMNS)}", file=sys.stderr)
            return 2
    with SessionLocal() as db:
        total = db.execute(select(func.count()).select_from(Property)).scalar_one()
        print(f"Total properties: {total}\n")
        for g in groupings:
            print(_table(stats_rows(db, g), [*g, "count"]) + "\n")
        runs = db.execute(select(IngestRun).order_by(IngestRun.id.desc()).limit(5)).scalars().all()
        if runs:
            rows = [
                (r.id, r.source_key, r.started_at.strftime("%Y-%m-%d %H:%M"), r.status,
                 r.inserted, r.updated, r.rejected, r.skipped)
                for r in runs
            ]  # fmt: skip
            print("Recent ingest runs:")
            print(_table(rows, ["id", "source", "started", "status", "ins", "upd", "rej", "skip"]))
    return 0


def cmd_reclassify(args) -> int:
    s = settings()
    changed = 0
    with SessionLocal() as db, SettingClassifier(s.ghsl_smod_path) as classifier:
        if not classifier.available:
            print("GHSL raster not available; nothing to do.", file=sys.stderr)
            return 1
        props = db.execute(select(Property)).scalars().all()
        for i in range(0, len(props), 5000):
            batch = props[i : i + 5000]
            results = classifier.classify_many(
                (p.lat, p.lng, p.property_type, p.area_m2) for p in batch
            )
            for p, (setting, raw) in zip(batch, results, strict=True):
                if (p.setting, p.setting_class_raw) != (setting, raw):
                    p.setting, p.setting_class_raw = setting, raw
                    changed += 1
            db.commit()
    print(f"Reclassified {len(props)} properties ({changed} changed).")
    return 0


def cmd_setting_data(args) -> int:
    s = settings()
    target = Path(s.ghsl_smod_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(s.scraper_user_agent, Path(s.ingest_cache_dir), default_delay=2)
    try:
        zpath = client.download(s.ghsl_smod_url, target.parent / "ghs_smod.zip", max_age_hours=0)
    except Exception as e:
        print(
            f"Download failed: {e}\nDownload the GHS-SMOD GeoTIFF (Mollweide, 1 km) manually from "
            f"https://human-settlement.emergency.copernicus.eu/download.php?ds=smod and save it "
            f"as {target}",
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()
    with zipfile.ZipFile(zpath) as zf:
        tifs = [n for n in zf.namelist() if n.lower().endswith(".tif")]
        if not tifs:
            print("No .tif in the downloaded archive", file=sys.stderr)
            return 1
        with zf.open(tifs[0]) as src, open(target, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
    zpath.unlink(missing_ok=True)
    print(f"Saved {tifs[0]} to {target}")
    return 0


def cmd_streetview_check(args) -> int:
    from ingest.streetview import StreetViewChecker, StreetViewCheckError

    try:
        checker = StreetViewChecker(settings().google_maps_api_key)
    except StreetViewCheckError as e:
        print(f"{e}. Add it to .env first.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        try:
            counts = checker.run(db, limit=args.limit)
        except StreetViewCheckError as e:
            print(f"Stopped: {e}", file=sys.stderr)
            return 1
        finally:
            checker.close()
    print(f"Street View check: {counts['ok']} ok, {counts['none']} without imagery.")
    return 0


def cmd_mapillary_check(args) -> int:
    from ingest.mapillary import MapillaryChecker, MapillaryCheckError

    try:
        checker = MapillaryChecker(settings().mapillary_token)
    except MapillaryCheckError as e:
        print(f"{e}. Add it to .env first.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        try:
            counts = checker.run(db, limit=args.limit)
        except MapillaryCheckError as e:
            print(f"Stopped: {e}", file=sys.stderr)
            return 1
        finally:
            checker.close()
    print(f"Mapillary check: {counts['ok']} with a photo, {counts['none']} without.")
    return 0


def cmd_strip_photos(args) -> int:
    with SessionLocal() as db:
        src = db.execute(select(Source).where(Source.key == args.source)).scalar_one_or_none()
        if src is None:
            print(f"Unknown source {args.source!r}", file=sys.stderr)
            return 2
        n = (
            db.query(Property)
            .filter(Property.source_id == src.id, Property.image_url.is_not(None))
            .update({Property.image_url: None})
        )
        db.commit()
    print(
        f"Removed {n} photo links from {args.source}. Also set `photos: false` for it in "
        f"sources.yaml so the next run doesn't bring them back."
    )
    return 0


def cmd_snapshot(args) -> int:
    from ingest import snapshot

    with SessionLocal() as db:
        if args.action == "export":
            if not args.source:
                print("usage: snapshot export SOURCE_KEY FILE", file=sys.stderr)
                return 2
            n = snapshot.export(
                db, args.source, args.file, notice=args.notice or "",
                playable_only=args.playable_only,
            )  # fmt: skip
            print(f"Exported {n} properties from {args.source} to {args.file}")
        else:
            c = snapshot.load(db, args.file)
            print(
                f"Loaded {args.file}: {c['inserted']} new, {c['updated']} updated, "
                f"{c['skipped_blocklisted']} blocklisted and {c['skipped_inactive']} removed "
                f"homes skipped."
            )
    return 0


def cmd_deactivate(args) -> int:
    with SessionLocal() as db:
        src = db.execute(select(Source).where(Source.key == args.source)).scalar_one_or_none()
        if src is None:
            print(f"Unknown source {args.source!r}", file=sys.stderr)
            return 2
        n = (
            db.query(Property)
            .filter(Property.source_id == src.id, Property.is_active.is_(True))
            .update({Property.is_active: False})
        )
        src.enabled = False
        db.commit()
    print(
        f"Deactivated {n} properties from {args.source}. Also set `enabled: false` for it in "
        f"sources.yaml so the next run doesn't re-import it."
    )
    return 0


def cmd_removals(args) -> int:
    with SessionLocal() as db:
        q = select(RemovalRequest).order_by(RemovalRequest.created_at)
        if not args.all:
            q = q.where(RemovalRequest.status == "pending")
        rows = db.execute(q).scalars().all()
    if not rows:
        print("No pending removal requests.")
        return 0
    for r in rows:
        print(f"#{r.id}  {r.created_at:%Y-%m-%d %H:%M}  [{r.status}]  {r.email}")
        print(f"     ref: {r.reference}")
        if r.message:
            print(f"     msg: {r.message}")
    print("\nRemove with: python -m ingest remove --property-id <uuid> --request <#>")
    return 0


def cmd_remove(args) -> int:
    with SessionLocal() as db:
        prop = db.get(Property, args.property_id)
        if prop is None:
            print(f"No property {args.property_id}", file=sys.stderr)
            return 2
        prop.is_active = False
        if db.get(Blocklist, (prop.source_id, prop.source_ref)) is None:
            db.add(Blocklist(source_id=prop.source_id, source_ref=prop.source_ref))
        if args.request:
            req = db.get(RemovalRequest, args.request)
            if req is not None:
                req.status = "done"
        db.commit()
    print(f"Removed {args.property_id} and blocklisted it; it will never be re-ingested.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ingest", description="Ballpark data ingestion")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one source or all enabled sources")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--source")
    g.add_argument("--all", action="store_true")
    r.add_argument("--limit", type=int, help="cap records this run (≤ max_records_per_run)")
    r.add_argument("--config", help="alternative sources.yaml")
    r.set_defaults(func=cmd_run)

    f = sub.add_parser("fx-update", help="refresh the FX cache")
    f.add_argument("--days", type=int, default=30)
    f.set_defaults(func=cmd_fx_update)

    st = sub.add_parser("stats", help="property counts")
    st.add_argument("--by", help=f"comma-separated: {','.join(STATS_COLUMNS)}")
    st.set_defaults(func=cmd_stats)

    rc = sub.add_parser("reclassify-settings", help="recompute setting for every property")
    rc.set_defaults(func=cmd_reclassify)

    sd = sub.add_parser("setting-data", help="manage the GHSL raster")
    sd.add_argument("action", choices=["download"])
    sd.set_defaults(func=cmd_setting_data)

    sv = sub.add_parser("streetview-check", help="fill pano_id for unchecked records")
    sv.add_argument("--limit", type=int, default=500)
    sv.set_defaults(func=cmd_streetview_check)

    mc = sub.add_parser("mapillary-check", help="find Mapillary photos for unchecked records")
    mc.add_argument("--limit", type=int, default=500)
    mc.set_defaults(func=cmd_mapillary_check)

    sp = sub.add_parser("strip-photos", help="forget a source's listing photo URLs")
    sp.add_argument("--source", required=True)
    sp.set_defaults(func=cmd_strip_photos)

    sn = sub.add_parser("snapshot", help="export/load a source's data as a file")
    sn.add_argument("action", choices=["export", "load"])
    sn.add_argument("source", nargs="?", help="source key (export only)")
    sn.add_argument("file", nargs="?")
    sn.add_argument("--notice", help="licence/attribution text stored in the file header")
    sn.add_argument("--playable-only", action="store_true",
                    help="export: skip district-precision records")  # fmt: skip
    sn.set_defaults(func=cmd_snapshot)

    de = sub.add_parser("deactivate", help="bulk-remove a source (takedown)")
    de.add_argument("--source", required=True)
    de.set_defaults(func=cmd_deactivate)

    rm = sub.add_parser("removals", help="list removal requests")
    rm.add_argument("--all", action="store_true", help="include handled requests")
    rm.set_defaults(func=cmd_removals)

    rr = sub.add_parser("remove", help="remove one record and blocklist it")
    rr.add_argument("--property-id", required=True)
    rr.add_argument("--request", type=int, help="mark this removal request as done")
    rr.set_defaults(func=cmd_remove)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "cmd", None) == "snapshot" and args.action == "load" and args.file is None:
        args.file, args.source = args.source, None  # `snapshot load FILE`
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO; geocoder URLs contain street addresses.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if "properties" not in inspect(engine).get_table_names():
        print("Database not migrated. Run `make migrate` first.", file=sys.stderr)
        return 2
    return args.func(args)
