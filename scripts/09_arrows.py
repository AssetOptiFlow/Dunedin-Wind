"""Dominant gust-direction arrows on a coarse grid (config.ARROW_SPACING_M).

Per coarse cell the dominant sector maximises
  w_s * mult_s(cell) * era5_gust99_s
i.e. the sector contributing most to local gust exposure (combining how often
strong gusts come from that direction with local terrain amplification).

Output: outputs/arrows.geojson - points (EPSG:4326) with
  bearing_deg : direction the wind comes FROM (met convention)
  speed_ms    : local p99 gust estimate (weighted surface)
  sector      : sector name (N, NE, ...)
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import analysis_grid


def main():
    clim = json.loads((C.OUTPUTS / "era5_climatology.json").read_text())
    sectors = clim["sectors"]
    w = np.array([s["freq_top_decile_gust"] for s in sectors])
    w = w / w.sum()
    g99 = np.array([s["gust_p99_ms"] for s in sectors])

    mults = []
    for s in sectors:
        with rasterio.open(C.OUTPUTS / "windninja" / f"mult_{s['sector']}.tif") as src:
            mults.append(src.read(1))
    mults = np.stack(mults)
    with rasterio.open(C.OUTPUTS / "gust" / "gust99_500m.tif") as src:
        gust = src.read(1)

    transform, width, height, _ = analysis_grid()
    step = max(1, round(C.ARROW_SPACING_M / C.GRID_RES_M))
    to_wgs = Transformer.from_crs(C.CRS_WORKING, C.CRS_WGS84, always_xy=True)

    contrib = w[:, None, None] * mults * g99[:, None, None]
    feats = []
    for r in range(step // 2, height, step):
        for c in range(step // 2, width, step):
            if not np.isfinite(gust[r, c]):
                continue
            s_idx = int(np.argmax(contrib[:, r, c]))
            x = transform.c + (c + 0.5) * transform.a
            y = transform.f + (r + 0.5) * transform.e
            lon, lat = to_wgs.transform(x, y)
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(lon, 5), round(lat, 5)]},
                "properties": {
                    "bearing_deg": C.SECTORS[s_idx],
                    "sector": C.SECTOR_NAMES[s_idx],
                    "speed_ms": round(float(gust[r, c]), 1),
                    "speed_kmh": round(float(gust[r, c]) * C.MS_TO_KMH),
                },
            })

    out = C.OUTPUTS / "arrows.geojson"
    out.write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, indent=1))
    print(f"{len(feats)} arrows at {C.ARROW_SPACING_M} m spacing -> {out}")


if __name__ == "__main__":
    main()
