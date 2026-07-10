"""Shared helpers for the Dunedin-Wind pipeline scripts."""
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C


def buffered_bbox_wgs84():
    """Bbox expanded by DEM_BUFFER_M, in degrees (WGS84)."""
    lat_mid = (C.BBOX["south"] + C.BBOX["north"]) / 2
    dlat = C.DEM_BUFFER_M / 111_320
    dlon = C.DEM_BUFFER_M / (111_320 * math.cos(math.radians(lat_mid)))
    return {
        "south": C.BBOX["south"] - dlat,
        "north": C.BBOX["north"] + dlat,
        "west": C.BBOX["west"] - dlon,
        "east": C.BBOX["east"] + dlon,
    }


def analysis_grid():
    """The snapped 500 m analysis grid over the (unbuffered) bbox in CRS_WORKING.

    Returns (transform, width, height, bounds).
    """
    l, b, r, t = transform_bounds(
        C.CRS_WGS84, C.CRS_WORKING,
        C.BBOX["west"], C.BBOX["south"], C.BBOX["east"], C.BBOX["north"],
    )
    res = C.GRID_RES_M
    l = math.floor(l / res) * res
    b = math.floor(b / res) * res
    r = math.ceil(r / res) * res
    t = math.ceil(t / res) * res
    width = round((r - l) / res)
    height = round((t - b) / res)
    transform = rasterio.transform.from_origin(l, t, res, res)
    return transform, width, height, (l, b, r, t)


def resample_to_grid(src_path, dst_path, resampling, dtype="float32", nodata=np.nan):
    """Warp a working-CRS raster onto the snapped 500 m analysis grid."""
    transform, width, height, _ = analysis_grid()
    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        profile.update(crs=C.CRS_WORKING, transform=transform, width=width,
                       height=height, dtype=dtype, nodata=nodata, count=1)
        dst_arr = np.full((height, width), nodata, dtype=dtype)
        reproject(
            source=rasterio.band(src, 1), destination=dst_arr,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=transform, dst_crs=C.CRS_WORKING,
            resampling=resampling, src_nodata=src.nodata, dst_nodata=nodata,
        )
    profile.pop("blockxsize", None); profile.pop("blockysize", None)
    with rasterio.open(dst_path, "w", **profile) as dst:
        dst.write(dst_arr, 1)
    return dst_arr


def reproject_to_wgs84(src_path, dst_path, resampling=Resampling.bilinear):
    """Reproject any raster to EPSG:4326 for delivery."""
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, C.CRS_WGS84, src.width, src.height, *src.bounds)
        profile = src.profile.copy()
        profile.update(crs=C.CRS_WGS84, transform=transform,
                       width=width, height=height)
        profile.pop("blockxsize", None); profile.pop("blockysize", None)
        with rasterio.open(dst_path, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=transform, dst_crs=C.CRS_WGS84,
                    resampling=resampling)
