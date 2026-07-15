"""Classify the gust surface into 5 numbered exposure zones and produce
smooth, cartographically generalised zone polygons (contour style, like
council wind-zone maps — curved boundaries, coherent areas).

Usage:
  python 08_zones.py --diagnose            # histogram + Jenks AND quantile
                                           # breaks -> checkpoint review
  python 08_zones.py --classify jenks      # after the user picks a scheme
  python 08_zones.py --classify quantile

Method (shared with 13_combined_map.py via _zones_core): Gaussian-smooth the
gust field, upsample, nested cumulative thresholds at the class breaks
(contouring — no gaps/overlaps), drop islands/holes < ZONE_MIN_AREA_KM2,
round boundaries, clip to land (edge-connected flood-fill ocean mask).
Breaks are computed on the SMOOTHED field (raw-field breaks empty the
extreme zones because smoothing compresses the tails).

The zone layer is GENERALISED CARTOGRAPHY; the continuous 500 m gust raster
remains the quantitative product. Zone 1 = lowest exposure ... Zone 5 highest.

Output:
  outputs/zones.geojson (EPSG:4326)
  outputs/zones_500m_wgs84.tif (byte raster of the smoothed classification)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
import _zones_core as core
from _util import resample_to_grid, reproject_to_wgs84

GUST_UTM = C.OUTPUTS / "gust" / "gust99_500m.tif"
DEM500 = C.DEM_DIR / "land_500m.tif"


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


def classify(scheme, raw_brk):
    # Ensure the 500 m land/dem grid exists (input to the land mask).
    if not DEM500.exists():
        resample_to_grid(C.DEM_DIR / "dem_utm.tif", DEM500, Resampling.average)

    smooth, finite, _ = core.smoothed_field(GUST_UTM)
    brk_smooth = breaks(smooth[finite].ravel())
    (C.DIAGNOSTICS / "zone_breaks_smoothed.json").write_text(
        json.dumps({"raw": raw_brk, "smoothed": brk_smooth}, indent=2))
    bs = np.array(brk_smooth[scheme])
    print(f"  breaks on smoothed field ({scheme}): "
          f"{[f'{b:.1f}' for b in bs]} m/s")

    gdf, zones_r, transform = core.generalise(GUST_UTM, DEM500, bs)
    gdf["label"] = gdf["zone"].map(lambda z: f"Zone {z}")
    gdf["gust_range_ms"] = gdf["zone"].map(
        lambda z: f"{bs[z-1]:.1f}-{bs[z]:.1f}")
    gdf["gust_range_kmh"] = gdf["zone"].map(
        lambda z: f"{bs[z-1]*C.MS_TO_KMH:.0f}-{bs[z]*C.MS_TO_KMH:.0f}")
    gdf["scheme"] = scheme
    gdf["note"] = (C.UNCERTAINTY_STATEMENT +
                   f" Zone boundaries generalised ({C.ZONE_GAUSS_SIGMA_M/1000:.0f} km "
                   "smoothing); consult the continuous layer for cell values.")
    for _, r in gdf.iterrows():
        print(f"  Zone {r['zone']}: {r['gust_range_ms']} m/s "
              f"({r['gust_range_kmh']} km/h), {r.geometry.area/1e6:.0f} km^2")
    gdf = gdf.to_crs(C.CRS_WGS84)
    out = C.OUTPUTS / "zones.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"wrote {out} (scheme={scheme}, generalised)")

    with rasterio.open(GUST_UTM) as src:
        prof = src.profile.copy()
    prof.update(dtype="uint8", nodata=0)
    zr_utm = C.OUTPUTS / "zones_500m.tif"
    with rasterio.open(zr_utm, "w", **prof) as dst:
        dst.write(zones_r, 1)
    reproject_to_wgs84(zr_utm, C.OUTPUTS / "zones_500m_wgs84.tif",
                       resampling=Resampling.nearest)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--diagnose", action="store_true")
    g.add_argument("--classify", choices=["jenks", "quantile"])
    args = ap.parse_args()

    with rasterio.open(GUST_UTM) as src:
        gust = src.read(1)
    values = gust[np.isfinite(gust)].ravel()
    brk = breaks(values)
    if args.diagnose:
        diagnose(values, brk)
    else:
        classify(args.classify, brk)


if __name__ == "__main__":
    main()
