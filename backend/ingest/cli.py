"""`python -m ingest ...` — run from the repo root (so `.env` and `./data` resolve).

run --source KEY | --all [--limit N]     run one / all enabled sources
images-check [--limit N]                 verify unchecked or stale photo URLs
refresh [--older-than-days N] [--limit]  re-check listings still live + photos still loading
fx-update [--days N]                     refresh FX cache (ECB + manual fallback CSV)
stats [--by country,setting]             counts by source / country / setting / images
reclassify-settings                      recompute urban/rural for every property
setting-data download                    download the GHSL GHS-SMOD raster
deactivate --source KEY                  bulk-remove a source (takedown)
reports [--resolve ID --action ...]      list / handle player photo reports
removals [--all]                         list removal requests
remove --property-id UUID [--request N]  remove one record + its photo URLs, blocklist it
csp [--write FILE]                       Content-Security-Policy from enabled image hosts
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.core.security import build_csp
from app.models import (
    Blocklist,
    IngestRun,
    PhotoReport,
    Property,
    PropertyImage,
    RemovalRequest,
    Source,
)
from ingest.config import load_sources, settings
from ingest.fx import FxService, ManualCsvFxProvider
from ingest.http import PoliteClient
from ingest.images import client_checker, run_images_check
from ingest.pipeline import IngestDeps, run_source, source_image_hosts
from ingest.refresh import run_refresh
from ingest.setting import SettingClassifier
from ingest.sources import PLUGINS
from ingest.sources.base import PluginContext

log = logging.getLogger("ingest")

STATS_COLUMNS = {
    "country": Property.country_code,
    "source": Source.key,
    "setting": Property.setting,
    "images": Property.images_status,
    "active": Property.is_active,
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


def _client(delay: float = 5.0, ttl: float = 72) -> PoliteClient:
    s = settings()
    return PoliteClient(
        s.scraper_user_agent, Path(s.ingest_cache_dir), default_delay=delay, cache_ttl_hours=ttl
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
    for key in keys:
        cfg = sources.get(key)
        if cfg is None:
            print(f"{key}: not configured in sources.yaml", file=sys.stderr)
            status = 2
            continue
        client = _client(cfg.delay_seconds, cfg.cache_ttl_hours)
        with SessionLocal() as db, SettingClassifier(s.ghsl_smod_path) as classifier:
            fx = _fx(db)
            plugin = PLUGINS[key](PluginContext(cache_dir=s.ingest_cache_dir))
            try:
                run = run_source(
                    db, plugin, cfg, IngestDeps(client, fx, classifier), limit=args.limit
                )
            finally:
                fx.close()
                client.close()
            print(
                f"{key}: {run.status} — inserted {run.inserted}, updated {run.updated}, "
                f"rejected {run.rejected}, skipped {run.skipped}, "
                f"dropped (country) {run.dropped_country}, duplicates {run.possible_duplicates}, "
                f"with working photos {(run.details or {}).get('images_ok', 0)}"
            )
            if run.message:
                print(f"  {run.message}")
            if run.status != "ok":
                status = 1
    return status


def cmd_images_check(args) -> int:
    client = _client()
    with SessionLocal() as db:
        try:
            c = run_images_check(db, client, limit=args.limit)
        finally:
            client.close()
    print(
        f"Photo check: {c['ok']} listings ok, {c['broken']} broken"
        + (f", {c['blocked_sources']} source(s) blocked" if c["blocked_sources"] else "")
    )
    return 0


def cmd_refresh(args) -> int:
    s = settings()
    sources = load_sources()
    plugins = {k: cls(PluginContext(cache_dir=s.ingest_cache_dir)) for k, cls in PLUGINS.items()}
    for k, p in plugins.items():
        cfg = sources.get(k)
        p.allow_midpoint = bool(cfg and cfg.settings.get("allow_price_range_midpoint"))
    client = _client()
    with SessionLocal() as db:
        try:
            c = run_refresh(db, plugins, client, client_checker(client),
                            older_than_days=args.older_than_days,
                            limit=args.limit or s.refresh_daily_limit)  # fmt: skip
        finally:
            client.close()
    print(
        f"Refresh: {c['checked']} checked, {c['live']} still live, {c['gone']} gone, "
        f"{c['skipped']} skipped, {c['deleted']} long-gone listings deleted."
    )
    return 0


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
    groupings = [args.by.split(",")] if args.by else [["source", "active"], ["country"], ["images"]]
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
        for p in props:
            setting, raw = classifier.classify(p.lat, p.lng, p.property_type, p.area_m2)
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
    client = _client(delay=2)
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


def _remove_property(db: Session, prop: Property) -> None:
    """Deactivate, delete its photo URLs, and blocklist it so it never comes back."""
    prop.is_active = False
    prop.images.clear()  # delete-orphan cascade removes the photo URL rows
    prop.images_status = "broken"
    if db.get(Blocklist, (prop.source_id, prop.source_ref)) is None:
        db.add(Blocklist(source_id=prop.source_id, source_ref=prop.source_ref))


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


def cmd_reports(args) -> int:
    with SessionLocal() as db:
        if args.resolve:
            rep = db.get(PhotoReport, args.resolve)
            if rep is None:
                print(f"No report #{args.resolve}", file=sys.stderr)
                return 2
            if args.action == "remove":
                _remove_property(db, db.get(Property, rep.property_id))
                rep.status = "resolved"
            elif args.action == "drop-photo":
                img = db.get(PropertyImage, (rep.property_id, rep.position))
                if img is not None:
                    db.delete(img)
                    db.flush()
                    from app.core.photos import recompute_images_status

                    prop = db.get(Property, rep.property_id)
                    db.refresh(prop)
                    recompute_images_status(prop)
                rep.status = "resolved"
            else:  # dismiss: nothing wrong, the home returns to play
                rep.status = "dismissed"
            db.commit()
            print(f"Report #{rep.id}: {rep.status}")
            return 0
        q = select(PhotoReport).order_by(PhotoReport.created_at)
        if not args.all:
            q = q.where(PhotoReport.status == "open")
        rows = db.execute(q).scalars().all()
        if not rows:
            print("No open photo reports.")
            return 0
        for r in rows:
            prop = db.get(Property, r.property_id)
            print(f"#{r.id}  {r.created_at:%Y-%m-%d %H:%M}  [{r.status}]  {r.reason}  "
                  f"photo {r.position}  property {r.property_id}")  # fmt: skip
            if prop and prop.listing_url:
                print(f"     listing: {prop.listing_url}")
        print("\nHandle with: python -m ingest reports --resolve <#> "
              "--action dismiss|drop-photo|remove")  # fmt: skip
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
        _remove_property(db, prop)
        if args.request:
            req = db.get(RemovalRequest, args.request)
            if req is not None:
                req.status = "done"
        db.commit()
    print(f"Removed {args.property_id} and its photo URLs; blocklisted so it never returns.")
    return 0


def current_csp() -> str:
    s = settings()
    sources = load_sources()
    hosts: list[str] = []
    for key, cfg in sources.items():
        if cfg.enabled and key in PLUGINS:
            hosts += source_image_hosts(PLUGINS[key](), cfg)
    return build_csp(hosts, s.osm_tile_url)


def cmd_csp(args) -> int:
    csp = current_csp()
    if args.write:
        Path(args.write).write_text(f'CSP="{csp}"\n', encoding="utf-8")
        print(f"Wrote {args.write}")
    else:
        print(csp)
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

    ic = sub.add_parser("images-check", help="verify unchecked or stale photo URLs")
    ic.add_argument("--limit", type=int, default=500)
    ic.set_defaults(func=cmd_images_check)

    rf = sub.add_parser("refresh", help="re-check listings still live + photos still loading")
    rf.add_argument("--older-than-days", type=int, default=14)
    rf.add_argument("--limit", type=int)
    rf.set_defaults(func=cmd_refresh)

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

    de = sub.add_parser("deactivate", help="bulk-remove a source (takedown)")
    de.add_argument("--source", required=True)
    de.set_defaults(func=cmd_deactivate)

    rp = sub.add_parser("reports", help="list / handle player photo reports")
    rp.add_argument("--all", action="store_true", help="include handled reports")
    rp.add_argument("--resolve", type=int, metavar="ID")
    rp.add_argument("--action", choices=["dismiss", "drop-photo", "remove"], default="dismiss")
    rp.set_defaults(func=cmd_reports)

    rm = sub.add_parser("removals", help="list removal requests")
    rm.add_argument("--all", action="store_true", help="include handled requests")
    rm.set_defaults(func=cmd_removals)

    rr = sub.add_parser("remove", help="remove one record + its photo URLs, blocklist it")
    rr.add_argument("--property-id", required=True)
    rr.add_argument("--request", type=int, help="mark this removal request as done")
    rr.set_defaults(func=cmd_remove)

    cs = sub.add_parser("csp", help="Content-Security-Policy from enabled sources' image hosts")
    cs.add_argument("--write", help="write CSP=... to this env file (for docker compose)")
    cs.set_defaults(func=cmd_csp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if "properties" not in inspect(engine).get_table_names():
        print("Database not migrated. Run `make migrate` first.", file=sys.stderr)
        return 2
    return args.func(args)
