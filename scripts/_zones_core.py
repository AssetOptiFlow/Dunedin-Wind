"""Zone generalisation core, shared by 08_zones.py (per-domain) and
13_combined_map.py (aligned two-domain product).

File-driven on purpose: no dependence on the config domain singleton, so one
process can generalise several domains. Only domain-independent constants
(smoothing, upsample, min area, boundary rounding, land threshold) come from
config.
"""
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import unary_union
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C


def clean(geom, min_area_m2):
    """Drop parts and interior holes smaller than min_area_m2."""
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    kept = []
    for p in polys:
        if p.area < min_area_m2:
            continue
        rings = [r for r in p.interiors if Polygon(r).area >= min_area_m2]
        kept.append(Polygon(p.exterior, rings))
    return unary_union(kept) if kept else None


def smooth_boundary(geom, d):
    """Round corners: buffer closing then opening with round joins."""
    return geom.buffer(d, join_style=1).buffer(-2 * d, join_style=1) \
               .buffer(d, join_style=1)


def smoothed_field(gust_utm_path):
    """Gaussian-smoothed gust field. Returns (smooth, finite, transform)."""
    with rasterio.open(gust_utm_path) as src:
        gust = src.read(1).astype("float64")
        transform = src.transform
        if src.nodata is not None:
            gust = np.where(gust == src.nodata, np.nan, gust)
    sigma = C.ZONE_GAUSS_SIGMA_M / C.GRID_RES_M
    finite = np.isfinite(gust)
    filled = np.where(finite, gust, np.nanmean(gust))
    return ndimage.gaussian_filter(filled, sigma=sigma), finite, transform


def land_mask_from(dem500_path):
    """Land = not connected-to-edge low terrain (drained plains stay land)."""
    with rasterio.open(dem500_path) as src:
        dem500 = src.read(1)
    low = np.nan_to_num(dem500) <= C.LAND_MIN_ELEV_M
    lbl, _ = ndimage.label(low)
    edge = (set(lbl[0, :]) | set(lbl[-1, :]) |
            set(lbl[:, 0]) | set(lbl[:, -1])) - {0}
    return ~np.isin(lbl, list(edge))


def generalise(gust_utm_path, dem500_path, breaks):
    """Contour-style generalised zone bands for one domain with the GIVEN
    breaks. Returns (bands GeoDataFrame in CRS_WORKING, zones uint8 array on
    the source 500 m grid, transform)."""
    bs = np.asarray(breaks, dtype=float)
    smooth, finite, transform = smoothed_field(gust_utm_path)
    up = C.ZONE_UPSAMPLE
    smooth_hi = ndimage.zoom(smooth, up, order=1)
    hi_transform = transform * transform.scale(1 / up, 1 / up)
    res_hi = C.GRID_RES_M / up
    min_area = C.ZONE_MIN_AREA_KM2 * 1e6

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

    land_mask = land_mask_from(dem500_path)
    land_hi = ndimage.zoom(land_mask.astype("float32"), up, order=1) > 0.5
    land_geoms = [shape(g) for g, v in features.shapes(
        land_hi.astype("uint8"), transform=hi_transform) if v == 1]
    land = clean(unary_union(land_geoms), min_area)
    land = smooth_boundary(land, C.ZONE_BOUNDARY_SMOOTH_M).simplify(res_hi)
    regions[1] = land
    for k in range(2, C.N_ZONES + 1):
        if regions.get(k) is not None and not regions[k].is_empty:
            regions[k] = regions[k].intersection(land)

    rows = []
    for k in range(1, C.N_ZONES + 1):
        geom = regions.get(k)
        if geom is None or geom.is_empty:
            continue
        nxt = regions.get(k + 1)
        band = geom.difference(nxt) if (nxt and not nxt.is_empty) else geom
        band = clean(band, min_area) or band
        rows.append({"zone": k, "geometry": band})

    gdf = gpd.GeoDataFrame(rows, crs=C.CRS_WORKING)
    zones_r = (np.digitize(smooth, bs[1:-1]) + 1).astype("uint8")
    zones_r = np.where(land_mask, zones_r, 0).astype("uint8")
    return gdf, zones_r, transform
