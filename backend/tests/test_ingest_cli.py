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
    monkeypatch.setattr("ingest.http.time.sleep", lambda s: None)  # skip the 5 s politeness waits
    cfg = cli_env / "sources.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "example_html": {
                    "enabled": True,
                    "delay_seconds": 2,
                    "base_url": fixture_site.url + "/",
                }
            }
        )
    )
    assert main(["run", "--all", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "example_html: ok — inserted 2" in out

    with SessionLocal() as db:
        assert db.query(Property).count() == 2

    assert main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "Total properties: 2" in out
    assert "example_html  2" in out
    assert "HR       1" in out and "PT       1" in out
    assert "unchecked  2" in out
    assert "Recent ingest runs" in out

    assert main(["stats", "--by", "country,setting"]) == 0
    assert "PT       unknown  1" in capsys.readouterr().out


def test_unknown_source_and_bad_stats_field(cli_env, capsys):
    assert main(["run", "--source", "nope"]) == 2
    assert main(["stats", "--by", "colour"]) == 2


def test_reclassify_without_raster(cli_env, capsys):
    assert main(["reclassify-settings"]) == 1
    assert "not available" in capsys.readouterr().err
