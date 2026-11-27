"""Urban / rural classification from the GHSL GHS-SMOD raster (Section 8.9).
Suburbs count as urban (owner decision 2026-11-27).

Source: European Commission JRC, GHSL Degree of Urbanisation settlement model (GHS-SMOD),
CC BY 4.0. One 1 km grid cell per value, Mollweide projection (ESRI:54009).
"""

import logging
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

# GHS-SMOD level-2 code -> our setting
SMOD_TO_SETTING: dict[int, str] = {
    30: "urban",  # urban centre
    23: "urban",  # dense urban cluster
    22: "urban",  # semi-dense urban cluster (owner decision: suburbs count as urban)
    21: "urban",  # suburban or peri-urban
    13: "rural",  # rural cluster
    12: "rural",  # low density rural
    11: "rural",  # very low density rural
    10: "unknown",  # water
}


def adjust_setting(
    setting: str, code: int | None, property_type: str | None, area_m2: float | None
) -> str:
    """Owner-tweakable adjustment rules applied after the raster lookup (Section 8.9).

    - An apartment in an urban-centre cell (30) stays urban.
    The spec's other rule (large house in a dense cluster -> suburban) no longer changes anything
    since suburbs count as urban (owner decision 2026-11-27). Add new rules here.
    """
    if code == 30 and property_type == "apartment":
        return "urban"
    return setting


def setting_for_code(code: int | None) -> str:
    if code is None:
        return "unknown"
    return SMOD_TO_SETTING.get(int(code), "unknown")


class SettingClassifier:
    """Open once per ingest run; `classify_many` samples thousands of points per second."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._ds = None
        self._transformer = None
        self.available = False
        if not self.path.exists():
            log.warning(
                "GHSL raster not found at %s — settings will be 'unknown'. "
                "Run `python -m ingest setting-data download`.",
                self.path,
            )
            return
        try:
            import rasterio
            from pyproj import Transformer

            self._ds = rasterio.open(self.path)
            self._transformer = Transformer.from_crs("EPSG:4326", self._ds.crs, always_xy=True)
            self._nodata = self._ds.nodata
            self.available = True
        except Exception as e:  # corrupt file, missing GDAL driver…
            log.warning("could not open GHSL raster %s: %s — settings will be 'unknown'", path, e)

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()
            self._ds = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def raw_codes(self, points: Iterable[tuple[float, float]]) -> list[int | None]:
        """GHS-SMOD codes for (lat, lng) points; None for nodata / outside the raster."""
        pts = list(points)
        if not self.available or not pts:
            return [None] * len(pts)
        lngs = [p[1] for p in pts]
        lats = [p[0] for p in pts]
        xs, ys = self._transformer.transform(lngs, lats)
        b = self._ds.bounds
        out: list[int | None] = [None] * len(pts)
        inside = [
            i
            for i, (x, y) in enumerate(zip(xs, ys, strict=True))
            if b.left <= x < b.right and b.bottom < y <= b.top
        ]
        if inside:
            coords = [(xs[i], ys[i]) for i in inside]
            for i, val in zip(inside, self._ds.sample(coords, indexes=1), strict=True):
                v = int(val[0])
                out[i] = None if (self._nodata is not None and v == self._nodata) else v
        return out

    def classify_many(
        self, items: Iterable[tuple[float, float, str | None, float | None]]
    ) -> list[tuple[str, int | None]]:
        """items: (lat, lng, property_type, area_m2) -> [(setting, raw_code)]"""
        items = list(items)
        codes = self.raw_codes((lat, lng) for lat, lng, _, _ in items)
        return [
            (adjust_setting(setting_for_code(code), code, ptype, area), code)
            for (_, _, ptype, area), code in zip(items, codes, strict=True)
        ]

    def classify(
        self,
        lat: float | None,
        lng: float | None,
        property_type: str | None = None,
        area_m2: float | None = None,
    ) -> tuple[str, int | None]:
        """Listings without coordinates are 'unknown' (and therefore not playable)."""
        if lat is None or lng is None:
            return "unknown", None
        return self.classify_many([(lat, lng, property_type, area_m2)])[0]
