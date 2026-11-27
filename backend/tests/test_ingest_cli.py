from datetime import date

import pytest
import yaml

from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.models import FxRate, Property
from ingest.cli import main


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Point the CLI's global DB (tests' temp DATABASE_URL) and caches at fresh locations."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = get_settings()
    monkeypatch.setattr(s, "ingest_cache_dir", str(tmp_path / "cache"))
    monkeypatch.setattr(s, "ghsl_smod_path", str(tmp_path / "missing.tif"))
    monkeypatch.setattr(s, "fx_manual_csv", str(tmp_path / "fx_manual.csv"))
    with SessionLocal() as db:
        for d in (date(2025, 10, 1), date(2022, 6, 15)):
            db.add(FxRate(date=d, currency="EUR", rate_to_usd=1.1))
        db.commit()
    yield tmp_path
    Base.metadata.drop_all(engine)


def test_run_and_stats(cli_env, fixture_site, monkeypatch, capsys):
    monkeypatch.setattr("ingest.http.time.sleep", lambda s: None)  # skip the politeness waits
    # The fixture photos live on the fictional images.example.test: pretend they load.
    monkeypatch.setattr("ingest.http.PoliteClient.check_image", lambda self, url, delay=1: True)
    cfg = cli_env / "sources.yaml"
    cfg.write_text(yaml.safe_dump({"example_html": {
        "enabled": True, "delay_seconds": 5, "base_url": fixture_site.url + "/",
        "image_hosts": ["images.example.test"]}}))  # fmt: skip
    assert main(["run", "--all", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "example_html: ok — inserted 2" in out and "with working photos 2" in out

    with SessionLocal() as db:
        assert db.query(Property).count() == 2

    assert main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "Total properties: 2" in out
    rows = {tuple(line.split()) for line in out.splitlines()}
    assert ("example_html", "True", "2") in rows
    assert ("HR", "1") in rows and ("PT", "1") in rows
    assert ("ok", "2") in rows
    assert "Recent ingest runs" in out

    assert main(["stats", "--by", "country,setting,images"]) == 0
    rows = {tuple(line.split()) for line in capsys.readouterr().out.splitlines()}
    assert ("PT", "unknown", "ok", "1") in rows  # no GHSL raster in tests -> unknown


def test_unknown_source_and_bad_stats_field(cli_env, capsys):
    assert main(["run", "--source", "nope"]) == 2
    assert main(["stats", "--by", "colour"]) == 2


def test_reclassify_without_raster(cli_env, capsys):
    assert main(["reclassify-settings"]) == 1
    assert "not available" in capsys.readouterr().err


def test_csp_lists_enabled_image_hosts(cli_env, capsys, tmp_path):
    from app.core.security import build_csp
    from ingest.cli import current_csp

    csp = build_csp(["images.example.test", "cdn.listings.test"],
                    "https://tile.openstreetmap.org/{z}/{x}/{y}.png")  # fmt: skip
    img = next(part for part in csp.split("; ") if part.startswith("img-src"))
    assert img == ("img-src 'self' https://cdn.listings.test https://images.example.test "
                   "https://tile.openstreetmap.org")  # fmt: skip
    assert "data:" not in csp and "*" not in csp
    # The shipped sources.yaml has nothing enabled -> only our site + the map tiles.
    assert "img-src 'self' https://tile.openstreetmap.org;" in current_csp()
    out = tmp_path / "csp.env"
    assert main(["csp", "--write", str(out)]) == 0
    assert out.read_text().startswith('CSP="default-src')
