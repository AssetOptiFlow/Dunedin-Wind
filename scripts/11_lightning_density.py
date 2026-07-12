"""Historical lightning ground-strike density layer (NZLDN via MfE, CC BY).

BLOCKS on a user action if the source raster is absent (like script 03's CDS
token gate): export MfE layer 52851 as GeoTIFF (EPSG:2193) to
data/lightning/lightning_density_2000_14.tif via a free Koordinates account.

Processing: clip to bbox+buffer (NZTM), /25 -> strikes/km^2/yr, then:
  outputs/lightning/lightning_density_5km_wgs84.tif      nearest (honest)
  outputs/lightning/lightning_density_display_wgs84.tif  upsampled + Gaussian
                                                          (webmap display only)
  outputs/lightning/lightning_meta.json                  stats + provenance

The density is NEVER resampled onto the 500 m analysis grid: ~10-30 strikes
per 5 km cell over 2000-14 near Dunedin cannot support finer resolution.

Exit codes: 0 with a warning if the source is absent (so full_refresh.py
never blocks on this optional layer); 1 on real processing errors.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import (calculate_default_transform, reproject,
                           Resampling, transform_bounds)
from rasterio.windows import from_bounds
from scipy import ndimage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import buffered_bbox_wgs84

OUT = C.OUTPUTS / "lightning"
CRS_NZTM = "EPSG:2193"


def gate():
    if C.LIGHTNING_SOURCE_TIF.exists() and C.LIGHTNING_SOURCE_TIF.stat().st_size > 0:
        return True
    print(
        "lightning layer SKIPPED - source raster not found.\n"
        f"To enable it, export the MfE layer to:\n  {C.LIGHTNING_SOURCE_TIF}\n"
        "Steps (free): 1) create an account at data.mfe.govt.nz;\n"
        f"  2) open {C.LIGHTNING_SOURCE_URL}\n"
        "  3) Export -> GeoTIFF, projection EPSG:2193 (NZTM), full extent or\n"
        "     an Otago clip; save with the filename above.\n"
        "Then rerun this script (or full_refresh.py)."
    )
    return False


def to_wgs84(arr, src_transform, src_crs, dst_path, resampling, nodata):
    l, b, r, t = (src_transform.c,
                  src_transform.f + src_transform.e * arr.shape[0],
                  src_transform.c + src_transform.a * arr.shape[1],
                  src_transform.f)
    transform, w, h = calculate_default_transform(
        src_crs, C.CRS_WGS84, arr.shape[1], arr.shape[0], l, b, r, t)
    dst = np.full((h, w), nodata, dtype="float32")
    reproject(source=arr, destination=dst,
              src_transform=src_transform, src_crs=src_crs,
              dst_transform=transform, dst_crs=C.CRS_WGS84,
              src_nodata=nodata, dst_nodata=nodata, resampling=resampling)
    profile = {"driver": "GTiff", "dtype": "float32", "count": 1,
               "crs": C.CRS_WGS84, "transform": transform,
               "width": w, "height": h, "nodata": nodata,
               "compress": "deflate"}
    with rasterio.open(dst_path, "w", **profile) as f:
        f.write(dst, 1)
    return dst


def main():
    if not gate():
        return  # exit 0: optional layer, never blocks the wind refresh

    OUT.mkdir(parents=True, exist_ok=True)
    bbox = buffered_bbox_wgs84()
    with rasterio.open(C.LIGHTNING_SOURCE_TIF) as src:
        if src.crs is None or src.crs.to_epsg() != 2193:
            sys.exit(f"expected EPSG:2193 source, got {src.crs}")
        l, b, r, t = transform_bounds(C.CRS_WGS84, CRS_NZTM,
                                      bbox["west"], bbox["south"],
                                      bbox["east"], bbox["north"])
        win = from_bounds(l, b, r, t, src.transform)
        data = src.read(1, window=win, boundless=True,
                        fill_value=src.nodata if src.nodata is not None else -9999)
        win_transform = src.window_transform(win)
        nodata = src.nodata if src.nodata is not None else -9999.0

    valid = (data != nodata) & np.isfinite(data)
    if not valid.any():
        sys.exit("no valid lightning cells inside the bbox - check the export extent")

    # Native units: ground strikes per 25 km^2 cell per year -> per km^2/yr.
    dens = np.where(valid, data / 25.0, np.nan).astype("float32")

    honest = to_wgs84(np.nan_to_num(dens, nan=-9999), win_transform, CRS_NZTM,
                      OUT / "lightning_density_5km_wgs84.tif",
                      Resampling.nearest, -9999.0)

    # Display copy: modest upsample + Gaussian, values preserved in scale.
    up = 8  # 5 km -> 625 m display texels
    filled = np.where(valid, dens, np.nanmean(dens))
    hi = ndimage.zoom(filled, up, order=1)
    hi = ndimage.gaussian_filter(hi, sigma=C.LIGHTNING_DISPLAY_SIGMA_M
                                 / (C.LIGHTNING_NATIVE_RES_M / up))
    mask_hi = ndimage.zoom(valid.astype("float32"), up, order=1) > 0.5
    hi = np.where(mask_hi, hi, -9999).astype("float32")
    hi_transform = win_transform * win_transform.scale(1 / up, 1 / up)
    to_wgs84(hi, hi_transform, CRS_NZTM,
             OUT / "lightning_density_display_wgs84.tif",
             Resampling.bilinear, -9999.0)

    vals = dens[np.isfinite(dens)]
    meta = {
        "source": "MfE layer 52851 'Lightning strike density, 2000-14' (NZLDN-derived)",
        "source_url": C.LIGHTNING_SOURCE_URL,
        "licence": C.LIGHTNING_ATTRIBUTION,
        "period": C.LIGHTNING_PERIOD,
        "native_resolution_m": C.LIGHTNING_NATIVE_RES_M,
        "display_smoothing_sigma_m": C.LIGHTNING_DISPLAY_SIGMA_M,
        "units": "ground strikes / km^2 / yr",
        "bbox_min": float(vals.min()), "bbox_max": float(vals.max()),
        "bbox_mean": float(vals.mean()),
        "n_native_cells": int(vals.size),
        "note": C.LIGHTNING_UNCERTAINTY,
    }
    (OUT / "lightning_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))

    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(np.where(honest == -9999, np.nan, honest), cmap="Blues")
    ax.set_title(f"Lightning ground-strike density {C.LIGHTNING_PERIOD} "
                 "(strikes/km$^2$/yr, 5 km native)")
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, shrink=0.7)
    (C.DIAGNOSTICS / "quicklooks").mkdir(parents=True, exist_ok=True)
    fig.savefig(C.DIAGNOSTICS / "quicklooks" / "lightning_density.png",
                dpi=120, bbox_inches="tight")
    print("done")


if __name__ == "__main__":
    main()
