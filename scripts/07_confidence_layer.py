"""Ordinal confidence layer (3=high, 2=medium, 1=low) per 500 m cell.

confidence = min(distance_score, terrain_score)   (weakest link)

  distance_score: 3 if nearest station <= STATION_DIST_HIGH_KM,
                  2 if <= STATION_DIST_MED_KM, else 1
                  (cells beyond MED also get no_station_within_threshold)
  terrain_score:  terciles of the actual TRI distribution (3=smoothest
                  tercile ... 1=most rugged - WindNinja's mass-conserving
                  solver degrades in complex terrain)

Station coordinates are public metadata (no CliFlo account); sources recorded
in webmap/stations.geojson. Distance bounds confidence only - no calibration.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import analysis_grid, reproject_to_wgs84

CONF_DIR = C.OUTPUTS / "confidence"


def main():
    transform, width, height, _ = analysis_grid()
    xs = transform.c + (np.arange(width) + 0.5) * transform.a
    ys = transform.f + (np.arange(height) + 0.5) * transform.e
    xx, yy = np.meshgrid(xs, ys)

    to_utm = Transformer.from_crs(C.CRS_WGS84, C.CRS_WORKING, always_xy=True)
    dist_km = np.full((height, width), np.inf)
    for st in C.STATIONS:
        sx, sy = to_utm.transform(st["lon"], st["lat"])
        dist_km = np.minimum(dist_km, np.hypot(xx - sx, yy - sy) / 1000)

    dist_score = np.where(dist_km <= C.STATION_DIST_HIGH_KM, 3,
                  np.where(dist_km <= C.STATION_DIST_MED_KM, 2, 1)).astype("uint8")
    no_station = dist_km > C.STATION_DIST_MED_KM

    with rasterio.open(C.OUTPUTS / "terrain" / "tri_500m.tif") as src:
        tri = src.read(1)
        prof = src.profile.copy()
    # Terciles over land cells only (TRI > 0): ocean cells are exactly 0 and
    # would degenerate the lower break to 0.0, unfairly penalising all land.
    land = tri[np.isfinite(tri) & (tri > 0)]
    t1, t2 = np.percentile(land, [33.3, 66.7])
    terrain_score = np.where(tri <= t1, 3, np.where(tri <= t2, 2, 1)).astype("uint8")

    conf = np.minimum(dist_score, terrain_score)

    CONF_DIR.mkdir(parents=True, exist_ok=True)
    prof.update(dtype="uint8", nodata=0)
    for arr, name in [(conf, "confidence_500m"),
                      (no_station.astype("uint8"), "no_station_flag_500m")]:
        p = CONF_DIR / f"{name}.tif"
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(arr, 1)
        reproject_to_wgs84(p, CONF_DIR / f"{name}_wgs84.tif",
                           resampling=rasterio.warp.Resampling.nearest)

    meta = {
        "thresholds_km": {"high": C.STATION_DIST_HIGH_KM,
                          "medium": C.STATION_DIST_MED_KM},
        "tri_terciles": [float(t1), float(t2)],
        "cells": {lvl: int((conf == v).sum())
                  for lvl, v in [("high", 3), ("medium", 2), ("low", 1)]},
        "no_station_cells": int(no_station.sum()),
        "max_station_distance_km": float(dist_km[np.isfinite(dist_km)].max()),
    }
    (CONF_DIR / "confidence_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))

    stations_gj = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "name": s["name"],
                "source": "Public NIWA/CliFlo station metadata (locations only; "
                          "no gust records used). Coordinates approximate to ~100 m.",
                "role": "confidence distance anchor - NOT a validation point",
            },
        } for s in C.STATIONS],
    }
    C.WEBMAP.mkdir(exist_ok=True)
    (C.WEBMAP / "stations.geojson").write_text(json.dumps(stations_gj, indent=2))
    print("done")


if __name__ == "__main__":
    main()
