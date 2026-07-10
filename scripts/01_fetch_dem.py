"""Fetch Copernicus GLO-30 DEM tiles (anonymous AWS S3), merge, clip to the
buffered bbox, and warp to the working CRS (UTM 59S) at 30 m.

Outputs:
  data/dem/dem_utm.tif    - EPSG:32759, 30 m, bbox + 5 km buffer (WindNinja input)
  data/dem/dem_wgs84.tif  - EPSG:4326 clip of the unbuffered bbox (delivery/QC)

Provenance: Copernicus DEM GLO-30, ESA/Airbus, via AWS Open Data
https://registry.opendata.aws/copernicus-dem/ (bucket copernicus-dem-30m,
anonymous HTTPS). Note: DSM — includes canopy/buildings.
"""
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import (calculate_default_transform, reproject,
                           Resampling, transform_bounds)
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import buffered_bbox_wgs84

TILE_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
            "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
            "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif")


def tile_names(bbox):
    """1x1 degree GLO-30 tiles intersecting bbox. Tile S46_E170 spans
    lat [-46,-45), lon [170,171)."""
    tiles = []
    for lat in range(math.floor(bbox["south"]), math.ceil(bbox["north"])):
        for lon in range(math.floor(bbox["west"]), math.ceil(bbox["east"])):
            lat_s = f"S{-lat:02d}" if lat < 0 else f"N{lat:02d}"
            lon_s = f"W{-lon:03d}" if lon < 0 else f"E{lon:03d}"
            tiles.append((lat_s, lon_s))
    return tiles


def main():
    C.DEM_DIR.mkdir(parents=True, exist_ok=True)
    bbox = buffered_bbox_wgs84()
    print(f"buffered bbox (WGS84): {bbox}")

    srcs = []
    for lat_s, lon_s in tile_names(bbox):
        url = TILE_URL.format(lat=lat_s, lon=lon_s)
        try:
            src = rasterio.open(url)
            srcs.append(src)
            print(f"  tile OK: {lat_s}_{lon_s}")
        except rasterio.errors.RasterioIOError:
            print(f"  tile absent (ocean?): {lat_s}_{lon_s}")
    if not srcs:
        sys.exit("no DEM tiles found — aborting")

    mosaic, transform = merge(
        srcs, bounds=(bbox["west"], bbox["south"], bbox["east"], bbox["north"]))
    profile = srcs[0].profile.copy()
    for s in srcs:
        s.close()
    profile.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2],
                   transform=transform, crs=C.CRS_WGS84, count=1,
                   compress="deflate")
    profile.pop("blockxsize", None); profile.pop("blockysize", None)

    merged_path = C.DEM_DIR / "dem_merged_wgs84.tif"
    with rasterio.open(merged_path, "w", **profile) as dst:
        dst.write(mosaic[0], 1)

    # Warp buffered mosaic to UTM 59S @ 30 m for WindNinja / terrain metrics.
    utm_path = C.DEM_DIR / "dem_utm.tif"
    with rasterio.open(merged_path) as src:
        dst_transform, w, h = calculate_default_transform(
            src.crs, C.CRS_WORKING, src.width, src.height, *src.bounds,
            resolution=C.DEM_RES_M)
        prof = src.profile.copy()
        prof.update(crs=C.CRS_WORKING, transform=dst_transform, width=w,
                    height=h, nodata=-9999.0, dtype="float32")
        with rasterio.open(utm_path, "w", **prof) as dst:
            reproject(source=rasterio.band(src, 1),
                      destination=rasterio.band(dst, 1),
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=dst_transform, dst_crs=C.CRS_WORKING,
                      resampling=Resampling.bilinear,
                      dst_nodata=-9999.0)

    # Unbuffered WGS84 clip for QC/delivery.
    clip_path = C.DEM_DIR / "dem_wgs84.tif"
    with rasterio.open(merged_path) as src:
        win = from_bounds(C.BBOX["west"], C.BBOX["south"],
                          C.BBOX["east"], C.BBOX["north"], src.transform)
        data = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(height=data.shape[0], width=data.shape[1],
                    transform=src.window_transform(win))
        with rasterio.open(clip_path, "w", **prof) as dst:
            dst.write(data, 1)

    with rasterio.open(utm_path) as src:
        a = src.read(1, masked=True)
        print(f"dem_utm.tif: {src.width}x{src.height} @ {C.DEM_RES_M} m, "
              f"elev {a.min():.0f}..{a.max():.0f} m (mean {a.mean():.0f})")
    print("done")


if __name__ == "__main__":
    main()
