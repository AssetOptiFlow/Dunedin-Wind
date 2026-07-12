"""Per-substation wind exposure summary from Aurora zone-substation reach
polygons (data/substations/aurora_zone_substations.geojson, converted from
the published Aurora Network GIS KML).

For each reach polygon intersecting the bbox: mean/max p99 gust, dominant
exposure zone, share of area in Zones 4-5, confidence mix, and a coverage
flag for polygons clipped by the analysis extent.

Outputs:
  outputs/substations_exposure.geojson   polygons + stats (webmap layer)
  outputs/substations_exposure.csv       ranked table (max gust desc)

Optional layer: self-skips (exit 0) if the source GeoJSON is absent.
NOTE: raw KML stays local (data/ is gitignored); publishing derived
boundaries in the public webmap needs a licence check — see BUILD_LOG.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

SRC = C.DATA / "substations" / "aurora_zone_substations.geojson"
CONF_NAMES = {3: "high", 2: "medium", 1: "low"}


def main():
    if not SRC.exists():
        print("substation layer SKIPPED - source not found:", SRC)
        return

    gdf = gpd.read_file(SRC)
    gdf = gdf[gdf.geometry.geom_type == "Polygon"].copy()

    with rasterio.open(C.OUTPUTS / "gust" / "gust99_500m_wgs84.tif") as s:
        gust = s.read(1)
        transform, shape = s.transform, s.shape
        if s.nodata is not None:
            gust = np.where(gust == s.nodata, np.nan, gust)
    with rasterio.open(C.OUTPUTS / "zones_500m_wgs84.tif") as s:
        zones = s.read(1)
    with rasterio.open(C.OUTPUTS / "confidence" / "confidence_500m_wgs84.tif") as s:
        conf = s.read(1)

    rows = []
    for _, r in gdf.iterrows():
        inside = ~geometry_mask([r.geometry], out_shape=shape,
                                transform=transform, invert=False,
                                all_touched=True)
        cells = inside & np.isfinite(gust)
        n = int(cells.sum())
        if n == 0:
            continue  # polygon entirely outside the analysis extent
        g = gust[cells]
        z = zones[cells & (zones > 0)]
        cf = conf[cells & (conf > 0)]
        # coverage: polygon area vs cells captured (flags bbox clipping)
        area_km2 = float(gpd.GeoSeries([r.geometry], crs=C.CRS_WGS84)
                         .to_crs(C.CRS_WORKING).area.iloc[0] / 1e6)
        covered_km2 = n * (C.GRID_RES_M / 1000) ** 2
        coverage = min(1.0, covered_km2 / max(area_km2, 1e-6))
        stats = {
            "name": r["name"], "region": r["region"], "gxp": r["gxp"],
            "voltage": r["voltage"], "feeders": r["feeders"],
            "area_km2": round(area_km2, 1),
            "n_cells": n,
            "coverage_pct": round(100 * coverage),
            "gust99_mean_kmh": round(float(np.nanmean(g)) * C.MS_TO_KMH),
            "gust99_max_kmh": round(float(np.nanmax(g)) * C.MS_TO_KMH),
            "dominant_zone": int(np.bincount(z).argmax()) if z.size else None,
            "pct_zone_4_5": round(100 * float((z >= 4).mean())) if z.size else None,
            "pct_conf_low": round(100 * float((cf == 1).mean())) if cf.size else None,
            "note": C.UNCERTAINTY_STATEMENT,
        }
        rows.append({**stats, "geometry": r.geometry})

    out = gpd.GeoDataFrame(rows, crs=C.CRS_WGS84)
    out = out.sort_values("gust99_max_kmh", ascending=False)
    out.to_file(C.OUTPUTS / "substations_exposure.geojson", driver="GeoJSON")
    out.drop(columns="geometry").to_csv(
        C.OUTPUTS / "substations_exposure.csv", index=False)

    print(f"{len(out)} substations summarised (of {len(gdf)} polygons):")
    cols = ["name", "gust99_mean_kmh", "gust99_max_kmh", "dominant_zone",
            "pct_zone_4_5", "pct_conf_low", "coverage_pct"]
    print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()
