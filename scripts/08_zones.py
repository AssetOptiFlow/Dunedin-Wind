"""Classify the gust surface into 5 numbered exposure zones and polygonise.

Usage:
  python 08_zones.py --diagnose            # histogram + Jenks AND quantile
                                           # breaks -> Checkpoint 5 review
  python 08_zones.py --classify jenks      # after the user picks a scheme
  python 08_zones.py --classify quantile

Zone 1 = lowest exposure ... Zone 5 = highest. Output:
  outputs/zones.geojson (EPSG:4326, dissolved, lightly simplified)
  outputs/zones_500m_wgs84.tif (byte raster, for the webmap ramp)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features
import geopandas as gpd
from shapely.geometry import shape
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

GUST_WGS84 = C.OUTPUTS / "gust" / "gust99_500m_wgs84.tif"


def breaks(values):
    import jenkspy
    jenks = jenkspy.jenks_breaks(values, n_classes=C.N_ZONES)
    quant = list(np.percentile(values, np.linspace(0, 100, C.N_ZONES + 1)))
    return {"jenks": [float(b) for b in jenks],
            "quantile": [float(b) for b in quant]}


def diagnose(values, brk):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharex=True)
    for ax, (name, bs) in zip(axes, brk.items()):
        ax.hist(values, bins=70, color="#43708a")
        for b in bs[1:-1]:
            ax.axvline(b, color="crimson", lw=1)
        counts = np.histogram(values, bins=bs)[0]
        ax.set_title(f"{name}: breaks {['%.1f' % b for b in bs]}\n"
                     f"cells/zone {list(counts)}")
        ax.set_xlabel("p99 gust (m/s)")
    fig.savefig(C.DIAGNOSTICS / "zone_breaks.png", dpi=120, bbox_inches="tight")
    (C.DIAGNOSTICS / "zone_breaks.json").write_text(json.dumps(brk, indent=2))
    print(json.dumps(brk, indent=2))
    print(f"diagnostics -> {C.DIAGNOSTICS / 'zone_breaks.png'}")


def classify(scheme, values, brk):
    bs = np.array(brk[scheme])
    bs[0], bs[-1] = -np.inf, np.inf
    with rasterio.open(GUST_WGS84) as src:
        gust = src.read(1)
        prof = src.profile.copy()
        transform = src.transform
    zones = np.digitize(gust, bs[1:-1]) + 1  # 1..5
    zones = np.where(np.isfinite(gust), zones, 0).astype("uint8")

    prof.update(dtype="uint8", nodata=0)
    zr_path = C.OUTPUTS / "zones_500m_wgs84.tif"
    with rasterio.open(zr_path, "w", **prof) as dst:
        dst.write(zones, 1)

    real_breaks = np.array(brk[scheme])
    geoms = []
    for geom, val in features.shapes(zones, transform=transform):
        if val > 0:
            geoms.append({"zone": int(val), "geometry": shape(geom)})
    gdf = gpd.GeoDataFrame(geoms, crs=C.CRS_WGS84)
    gdf = gdf.dissolve(by="zone", as_index=False)
    gdf["geometry"] = gdf.geometry.simplify(0.0008)
    gdf["label"] = gdf["zone"].map(lambda z: f"Zone {z}")
    gdf["gust_range_ms"] = gdf["zone"].map(
        lambda z: f"{real_breaks[z-1]:.1f}-{real_breaks[z]:.1f}")
    gdf["scheme"] = scheme
    gdf["note"] = C.UNCERTAINTY_STATEMENT
    out = C.OUTPUTS / "zones.geojson"
    gdf.to_file(out, driver="GeoJSON")
    for _, r in gdf.iterrows():
        print(f"  {r['label']}: {r['gust_range_ms']} m/s")
    print(f"wrote {out} (scheme={scheme})")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--diagnose", action="store_true")
    g.add_argument("--classify", choices=["jenks", "quantile"])
    args = ap.parse_args()

    with rasterio.open(GUST_WGS84) as src:
        gust = src.read(1)
    values = gust[np.isfinite(gust)].ravel()
    brk = breaks(values)
    if args.diagnose:
        diagnose(values, brk)
    else:
        classify(args.classify, values, brk)


if __name__ == "__main__":
    main()
