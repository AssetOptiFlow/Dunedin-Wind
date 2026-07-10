"""Classify the gust surface into 5 numbered exposure zones and produce
smooth, cartographically generalised zone polygons (contour style, like
council wind-zone maps — curved boundaries, coherent areas).

Usage:
  python 08_zones.py --diagnose            # histogram + Jenks AND quantile
                                           # breaks -> Checkpoint 5 review
  python 08_zones.py --classify jenks      # after the user picks a scheme
  python 08_zones.py --classify quantile

Method: Gaussian-smooth the gust field (config.ZONE_GAUSS_SIGMA_M), upsample,
take nested cumulative thresholds at the class breaks (contouring — adjacent
zones can never gap), drop islands/holes < ZONE_MIN_AREA_KM2, round the
boundaries (buffer closing/opening), difference into per-zone bands.

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
from rasterio import features
from rasterio.warp import Resampling
from scipy import ndimage
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import analysis_grid, reproject_to_wgs84

GUST_UTM = C.OUTPUTS / "gust" / "gust99_500m.tif"


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


def clean(geom, min_area_m2):
    """Drop parts and interior holes smaller than min_area_m2."""
    from shapely.geometry import Polygon, MultiPolygon
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    kept = []
    for p in polys:
        if p.area < min_area_m2:
            continue
        rings = [r for r in p.interiors
                 if Polygon(r).area >= min_area_m2]
        kept.append(Polygon(p.exterior, rings))
    return unary_union(kept) if kept else None


def smooth_boundary(geom, d):
    """Round corners: buffer closing then opening with round joins."""
    return geom.buffer(d, join_style=1).buffer(-2 * d, join_style=1) \
               .buffer(d, join_style=1)


def classify(scheme, values, brk):
    with rasterio.open(GUST_UTM) as src:
        gust = src.read(1).astype("float64")
        transform = src.transform
        prof = src.profile.copy()

    # 1. Smooth the field (sigma in cells), then upsample for curve quality.
    sigma = C.ZONE_GAUSS_SIGMA_M / C.GRID_RES_M
    finite = np.isfinite(gust)
    filled = np.where(finite, gust, np.nanmean(gust))
    smooth = ndimage.gaussian_filter(filled, sigma=sigma)

    # Breaks are recomputed on the SMOOTHED field: smoothing compresses the
    # tails, so raw-field breaks would empty the extreme zones. Both sets go
    # to the diagnostics JSON for traceability.
    brk_smooth = breaks(smooth[finite].ravel())
    (C.DIAGNOSTICS / "zone_breaks_smoothed.json").write_text(
        json.dumps({"raw": brk, "smoothed": brk_smooth}, indent=2))
    bs = np.array(brk_smooth[scheme])
    print(f"  breaks on smoothed field ({scheme}): "
          f"{[f'{b:.1f}' for b in bs]} m/s")
    up = C.ZONE_UPSAMPLE
    smooth_hi = ndimage.zoom(smooth, up, order=1)
    hi_transform = transform * transform.scale(1 / up, 1 / up)
    res_hi = C.GRID_RES_M / up
    min_area = C.ZONE_MIN_AREA_KM2 * 1e6

    # 2. Nested cumulative regions: R_k = area with smoothed gust >= break k.
    #    Contour-style, so adjacent zones can never gap or overlap.
    regions = {}
    for k in range(2, C.N_ZONES + 1):
        mask = (smooth_hi >= bs[k - 1]).astype("uint8")
        geoms = [shape(g) for g, v in features.shapes(
            mask, transform=hi_transform) if v == 1]
        geom = unary_union(geoms) if geoms else None
        if geom is not None and not geom.is_empty:
            geom = clean(geom, min_area)
        if geom is not None and not geom.is_empty:
            geom = smooth_boundary(geom, C.ZONE_BOUNDARY_SMOOTH_M)
            geom = geom.simplify(res_hi)
            geom = clean(geom, min_area)
        regions[k] = geom

    # Base for Zone 1 = land within the analysis extent (council-map style:
    # water is unzoned; the continuous raster still covers it).
    from _util import resample_to_grid
    dem500 = resample_to_grid(C.DEM_DIR / "dem_utm.tif",
                              C.DEM_DIR / "land_500m.tif", Resampling.average)
    # Ocean = low cells CONNECTED TO THE MAP EDGE (flood fill). A plain
    # elevation cut would wrongly drop the below-sea-level parts of the
    # drained Taieri Plain; enclosed low land stays zoned, sea/harbour don't.
    low = np.nan_to_num(dem500) <= C.LAND_MIN_ELEV_M
    lbl, _ = ndimage.label(low)
    edge = (set(lbl[0, :]) | set(lbl[-1, :]) |
            set(lbl[:, 0]) | set(lbl[:, -1])) - {0}
    land_mask = ~np.isin(lbl, list(edge))
    land_hi = ndimage.zoom(land_mask.astype("float32"), up, order=1) > 0.5
    land_geoms = [shape(g) for g, v in features.shapes(
        land_hi.astype("uint8"), transform=hi_transform) if v == 1]
    land = clean(unary_union(land_geoms), min_area)
    land = smooth_boundary(land, C.ZONE_BOUNDARY_SMOOTH_M).simplify(res_hi)
    regions[1] = land
    for k in range(2, C.N_ZONES + 1):
        if regions.get(k) is not None and not regions[k].is_empty:
            regions[k] = regions[k].intersection(land)

    # 3. Difference nested regions into per-zone bands.
    rows = []
    for k in range(1, C.N_ZONES + 1):
        geom = regions.get(k)
        if geom is None or geom.is_empty:
            print(f"  Zone {k}: empty after generalisation")
            continue
        nxt = regions.get(k + 1)
        band = geom.difference(nxt) if (nxt and not nxt.is_empty) else geom
        band = clean(band, min_area) or band
        rows.append({"zone": k, "geometry": band})
        print(f"  Zone {k}: {bs[k-1]:.1f}-{bs[k]:.1f} m/s "
              f"({bs[k-1]*C.MS_TO_KMH:.0f}-{bs[k]*C.MS_TO_KMH:.0f} km/h), "
              f"{band.area/1e6:.0f} km^2")

    gdf = gpd.GeoDataFrame(rows, crs=C.CRS_WORKING)
    gdf["label"] = gdf["zone"].map(lambda z: f"Zone {z}")
    gdf["gust_range_ms"] = gdf["zone"].map(
        lambda z: f"{bs[z-1]:.1f}-{bs[z]:.1f}")
    gdf["gust_range_kmh"] = gdf["zone"].map(
        lambda z: f"{bs[z-1]*C.MS_TO_KMH:.0f}-{bs[z]*C.MS_TO_KMH:.0f}")
    gdf["scheme"] = scheme
    gdf["note"] = (C.UNCERTAINTY_STATEMENT +
                   f" Zone boundaries generalised ({C.ZONE_GAUSS_SIGMA_M/1000:.0f} km "
                   "smoothing); consult the continuous layer for cell values.")
    gdf = gdf.to_crs(C.CRS_WGS84)
    out = C.OUTPUTS / "zones.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"wrote {out} (scheme={scheme}, generalised)")

    # 4. Matching byte raster (smoothed classification, 500 m).
    zones_r = (np.digitize(smooth, bs[1:-1]) + 1).astype("uint8")
    zones_r = np.where(land_mask, zones_r, 0).astype("uint8")
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
        classify(args.classify, values, brk)


if __name__ == "__main__":
    main()
