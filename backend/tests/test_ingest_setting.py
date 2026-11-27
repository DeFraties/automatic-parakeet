import time

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from ingest.setting import SMOD_TO_SETTING, SettingClassifier, adjust_setting, setting_for_code

MOLLWEIDE = "ESRI:54009"
CENTER = (38.7139, -9.1394)  # Lisbon (lat, lng)
NODATA = 255

# (row, col) -> GHS-SMOD code in a 10x10 km synthetic grid
CELLS = {
    (1, 1): 30,
    (1, 4): 23,
    (4, 1): 22,
    (4, 4): 21,
    (7, 1): 13,
    (7, 4): 12,
    (7, 7): 11,
    (1, 7): 10,
    (9, 9): NODATA,
}


@pytest.fixture(scope="module")
def raster(tmp_path_factory):
    fwd = Transformer.from_crs("EPSG:4326", MOLLWEIDE, always_xy=True)
    inv = Transformer.from_crs(MOLLWEIDE, "EPSG:4326", always_xy=True)
    x0, y0 = fwd.transform(CENTER[1], CENTER[0])
    left, top = x0 - 5000, y0 + 5000
    data = np.full((10, 10), 11, dtype=np.uint8)
    for (r, c), code in CELLS.items():
        data[r, c] = code
    path = tmp_path_factory.mktemp("ghsl") / "smod.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="uint8",
        crs=MOLLWEIDE,
        transform=from_origin(left, top, 1000, 1000),
        nodata=NODATA,
    ) as dst:
        dst.write(data, 1)

    def point(r, c):  # lat/lng at the center of cell (r, c)
        lng, lat = inv.transform(left + (c + 0.5) * 1000, top - (r + 0.5) * 1000)
        return lat, lng

    return path, point


@pytest.mark.parametrize(
    "cell,expected",
    [
        ((1, 1), "urban"),
        ((1, 4), "urban"),
        ((4, 1), "urban"),
        ((4, 4), "urban"),
        ((7, 1), "rural"),
        ((7, 4), "rural"),
        ((7, 7), "rural"),
        ((1, 7), "unknown"),
        ((9, 9), "unknown"),
    ],
)
def test_known_points(raster, cell, expected):
    path, point = raster
    with SettingClassifier(path) as clf:
        setting, raw = clf.classify(*point(*cell))
    assert setting == expected
    assert raw == (None if CELLS[cell] == NODATA else CELLS[cell])


def test_point_outside_raster_is_unknown(raster):
    path, _ = raster
    with SettingClassifier(path) as clf:
        assert clf.classify(35.68, 139.69) == ("unknown", None)  # Tokyo


def test_suburbs_count_as_urban(raster):
    path, point = raster
    with SettingClassifier(path) as clf:
        assert clf.classify(*point(4, 1))[0] == "urban"  # code 22
        assert clf.classify(*point(4, 4))[0] == "urban"  # code 21
        assert clf.classify(*point(1, 4), "house", 450)[0] == "urban"  # big house, code 23
        assert clf.classify(*point(1, 1), "apartment", 80)[0] == "urban"


def test_adjust_setting_function():
    assert adjust_setting("urban", 30, "apartment", 50) == "urban"
    assert adjust_setting("rural", 13, "house", 500) == "rural"


def test_missing_coordinates_are_unknown(raster):
    path, _ = raster
    with SettingClassifier(path) as clf:
        assert clf.classify(None, None, "house", 100) == ("unknown", None)


def test_code_mapping_matches_spec():
    assert {c: setting_for_code(c) for c in SMOD_TO_SETTING} == SMOD_TO_SETTING
    assert setting_for_code(None) == "unknown"
    assert setting_for_code(99) == "unknown"


def test_missing_raster_gives_unknown(tmp_path, caplog):
    with SettingClassifier(tmp_path / "nope.tif") as clf:
        assert not clf.available
        assert clf.classify(38.7, -9.1) == ("unknown", None)
    assert "not found" in caplog.text


def test_corrupt_raster_gives_unknown(tmp_path):
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not a tiff")
    with SettingClassifier(bad) as clf:
        assert clf.classify(38.7, -9.1) == ("unknown", None)


def test_fast_batch_sampling(raster):
    path, point = raster
    pts = [(*point(i % 10, (i * 7) % 10), "house", 100.0) for i in range(5000)]
    with SettingClassifier(path) as clf:
        t = time.perf_counter()
        out = clf.classify_many(pts)
        elapsed = time.perf_counter() - t
    assert len(out) == 5000
    assert elapsed < 2.0, f"{5000 / elapsed:.0f} points/s"
