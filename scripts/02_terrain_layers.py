"""Derive terrain layers from the 30 m UTM DEM and aggregate to the 500 m
analysis grid.

30 m metrics (data/dem/):
  slope (richdem), aspect (richdem), TRI (whitebox RuggednessIndex),
  horizon angle for 8 azimuths (whitebox HorizonAngle, 2 km search) —
  the upwind horizon angle for wind FROM each sector: high = sheltered,
  low/negative = exposed.

500 m aggregates (outputs/terrain/):
  slope_500m (mean), aspect_500m (circular mean), tri_500m (mean),
  tri_max_500m (max), horizon_<sector>_500m (mean), all EPSG:32759 +
  EPSG:4326 delivery copies.

Quicklooks (outputs/diagnostics/quicklooks/): hillshade, slope, TRI,
horizon_W — for Checkpoint 1 review.
"""
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
from _util import resample_to_grid, reproject_to_wgs84

TERRAIN = C.OUTPUTS / "terrain"
QUICKLOOKS = C.DIAGNOSTICS / "quicklooks"
DEM_UTM = C.DEM_DIR / "dem_utm.tif"
HORIZON_SEARCH_M = 2000.0


def richdem_metrics():
    # richdem's LoadGDAL/SaveGDAL need the osgeo bindings, which this env
    # doesn't ship — go through rasterio + rd.rdarray instead.
    import richdem as rd
    with rasterio.open(DEM_UTM) as src:
        arr = src.read(1).astype("float64")
        prof = src.profile.copy()
        gt = src.transform.to_gdal()
        nodata = src.nodata if src.nodata is not None else -9999.0
    dem = rd.rdarray(arr, no_data=nodata)
    dem.geotransform = gt
    prof.update(dtype="float32", nodata=-9999.0)
    for attrib, name in [("slope_degrees", "slope"), ("aspect", "aspect")]:
        out = rd.TerrainAttribute(dem, attrib=attrib)
        with rasterio.open(C.DEM_DIR / f"{name}_30m.tif", "w", **prof) as dst:
            dst.write(np.asarray(out, dtype="float32"), 1)
        print(f"  richdem {name} done")


def whitebox_metrics():
    from whitebox import WhiteboxTools
    wbt = WhiteboxTools()
    wbt.verbose = False
    wbt.set_working_dir(str(C.DEM_DIR))

    wbt.ruggedness_index("dem_utm.tif", "tri_30m.tif")
    print("  whitebox TRI done")
    for az, name in zip(C.SECTORS, C.SECTOR_NAMES):
        wbt.horizon_angle("dem_utm.tif", f"horizon_{name}_30m.tif",
                          azimuth=float(az), max_dist=HORIZON_SEARCH_M)
        print(f"  whitebox horizon {name} ({az} deg) done")


def aggregate_500m():
    TERRAIN.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("slope_30m.tif", "slope_500m.tif", Resampling.average),
        ("tri_30m.tif", "tri_500m.tif", Resampling.average),
        ("tri_30m.tif", "tri_max_500m.tif", Resampling.max),
    ]
    jobs += [(f"horizon_{n}_30m.tif", f"horizon_{n}_500m.tif",
              Resampling.average) for n in C.SECTOR_NAMES]
    for src_name, dst_name, method in jobs:
        resample_to_grid(C.DEM_DIR / src_name, TERRAIN / dst_name, method)
        reproject_to_wgs84(TERRAIN / dst_name,
                           TERRAIN / dst_name.replace(".tif", "_wgs84.tif"))
        print(f"  500m {dst_name} done")

    # Aspect needs a circular mean: average sin/cos at 30 m, recombine.
    with rasterio.open(C.DEM_DIR / "aspect_30m.tif") as src:
        asp = src.read(1)
        prof = src.profile.copy()
        rad = np.deg2rad(asp)
        for arr, name in [(np.sin(rad), "aspect_sin"), (np.cos(rad), "aspect_cos")]:
            with rasterio.open(C.DEM_DIR / f"{name}_30m.tif", "w", **prof) as dst:
                dst.write(arr.astype("float32"), 1)
    s = resample_to_grid(C.DEM_DIR / "aspect_sin_30m.tif",
                         TERRAIN / "_aspect_sin_500m.tif", Resampling.average)
    c = resample_to_grid(C.DEM_DIR / "aspect_cos_30m.tif",
                         TERRAIN / "_aspect_cos_500m.tif", Resampling.average)
    aspect = (np.rad2deg(np.arctan2(s, c)) + 360) % 360
    with rasterio.open(TERRAIN / "_aspect_sin_500m.tif") as ref:
        prof = ref.profile.copy()
    with rasterio.open(TERRAIN / "aspect_500m.tif", "w", **prof) as dst:
        dst.write(aspect.astype("float32"), 1)
    reproject_to_wgs84(TERRAIN / "aspect_500m.tif",
                       TERRAIN / "aspect_500m_wgs84.tif",
                       resampling=Resampling.nearest)
    print("  500m aspect (circular mean) done")


def quicklooks():
    QUICKLOOKS.mkdir(parents=True, exist_ok=True)

    def show(path, title, cmap, out, vmin=None, vmax=None):
        with rasterio.open(path) as src:
            a = src.read(1, masked=True)
        fig, ax = plt.subplots(figsize=(10, 6))
        im = ax.imshow(a, cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_title(title)
        ax.set_axis_off()
        fig.colorbar(im, ax=ax, shrink=0.7)
        fig.savefig(out, dpi=120, bbox_inches="tight")
        plt.close(fig)

    # Hillshade from the DEM for orientation.
    with rasterio.open(DEM_UTM) as src:
        dem = src.read(1, masked=True).filled(np.nan)
    gy, gx = np.gradient(dem, C.DEM_RES_M)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.deg2rad(315), np.deg2rad(45)
    hs = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(az - aspect)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.imshow(hs, cmap="gray")
    ax.set_title("Hillshade (GLO-30, UTM 59S, 30 m, bbox + 5 km buffer)")
    ax.set_axis_off()
    fig.savefig(QUICKLOOKS / "hillshade.png", dpi=120, bbox_inches="tight")
    plt.close(fig)

    show(TERRAIN / "slope_500m.tif", "Slope (deg, mean to 500 m)",
         "viridis", QUICKLOOKS / "slope_500m.png")
    show(TERRAIN / "tri_500m.tif", "Terrain Ruggedness Index (mean to 500 m)",
         "magma", QUICKLOOKS / "tri_500m.png")
    show(TERRAIN / "horizon_W_500m.tif",
         "Horizon angle looking W (deg; low = exposed to W wind)",
         "RdBu", QUICKLOOKS / "horizon_W_500m.png", vmin=-15, vmax=15)
    print(f"  quicklooks in {QUICKLOOKS}")


def main():
    if not DEM_UTM.exists():
        sys.exit("run 01_fetch_dem.py first")
    print("richdem metrics...")
    richdem_metrics()
    print("whitebox metrics...")
    whitebox_metrics()
    print("aggregating to 500 m...")
    aggregate_500m()
    print("quicklooks...")
    quicklooks()
    print("done")


if __name__ == "__main__":
    main()
