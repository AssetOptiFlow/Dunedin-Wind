"""Run WindNinja for the 8 directional sectors and derive terrain speed-up
multiplier rasters on the 500 m analysis grid.

Initialization: domainAverageInitialization, non-diurnal, mass-conserving
solver (momentum_flag=false) — the appropriate mode for a climatological
domain-average approach (verified against WindNinja 3.12.2 docs and CLI).
Input speed per sector = ERA5 per-sector 99th-percentile 10 m speed from
outputs/era5_climatology.json (Checkpoint 3 approves this matrix).

The 3.12.2 win64 build has no GeoTIFF writer, so we take AAIGRID ASCII
output (*_vel.asc, UTM) at 500 m and read it with rasterio.

Outputs:
  data/windninja/<sector>/...            raw WindNinja outputs + cfg + log
  outputs/windninja/mult_<sector>.tif    speed-up multiplier, 500 m grid, 32759
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import resample_to_grid

WN_OUT = C.OUTPUTS / "windninja"

CFG_TEMPLATE = """\
num_threads = {threads}
elevation_file = {dem}
initialization_method = domainAverageInitialization
time_zone = Pacific/Auckland
input_speed = {speed:.2f}
input_speed_units = mps
output_speed_units = mps
input_direction = {direction}
input_wind_height = {height}
units_input_wind_height = m
output_wind_height = {height}
units_output_wind_height = m
vegetation = {vegetation}
diurnal_winds = false
momentum_flag = false
mesh_resolution = {mesh}
units_mesh_resolution = m
write_ascii_output = true
ascii_out_aaigrid = true
ascii_out_utm = true
ascii_out_resolution = {out_res}
units_ascii_out_resolution = m
output_path = {out_path}
"""


def run_sector(name: str, direction: int, speed: float) -> Path:
    """Run one sector; returns path to the *_vel.asc output."""
    run_dir = C.WINDNINJA_DIR / name
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = run_dir / f"{name}.cfg"
    cfg.write_text(CFG_TEMPLATE.format(
        threads=C.WN_NUM_THREADS, dem=C.DEM_DIR / "dem_utm.tif",
        speed=speed, direction=direction, height=C.WN_WIND_HEIGHT_M,
        vegetation=C.WN_VEGETATION, mesh=C.WN_MESH_RES_M,
        out_res=C.GRID_RES_M, out_path=run_dir))

    existing = list(run_dir.glob("*_vel.asc"))
    if existing:
        print(f"  {name}: output exists, skipping run")
        return existing[0]

    print(f"  {name}: dir {direction} deg @ {speed:.1f} m/s ...", flush=True)
    proc = subprocess.run([str(C.WINDNINJA_CLI), str(cfg)],
                          capture_output=True, text=True)
    (run_dir / "run.log").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    vel = list(run_dir.glob("*_vel.asc"))
    if proc.returncode != 0 or not vel:
        sys.exit(f"WindNinja failed for {name} (exit {proc.returncode}) — "
                 f"see {run_dir / 'run.log'}")
    return vel[0]


def multiplier_raster(name: str, vel_asc: Path, input_speed: float):
    """Speed-up multiplier = simulated speed / domain-average input speed,
    clipped to config.MULT_CLIP, resampled onto the 500 m analysis grid."""
    WN_OUT.mkdir(parents=True, exist_ok=True)
    # The .asc has no CRS; it is UTM on the DEM's zone (EPSG:32759).
    tmp = vel_asc.with_suffix(".tif")
    with rasterio.open(vel_asc) as src:
        arr = src.read(1).astype("float32")
        prof = src.profile.copy()
        prof.update(driver="GTiff", crs=C.CRS_WORKING, dtype="float32",
                    nodata=-9999.0)
    mult = arr / float(input_speed)
    n_clip = int(((mult < C.MULT_CLIP[0]) | (mult > C.MULT_CLIP[1])).sum())
    mult = np.clip(mult, *C.MULT_CLIP)
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(mult, 1)
    out = WN_OUT / f"mult_{name}.tif"
    grid = resample_to_grid(tmp, out, Resampling.bilinear)
    print(f"  {name}: mult {np.nanmin(grid):.2f}..{np.nanmax(grid):.2f} "
          f"(mean {np.nanmean(grid):.2f}, {n_clip} cells clipped)")


def main():
    clim = json.loads((C.OUTPUTS / "era5_climatology.json").read_text())
    speeds = {s["sector"]: s["speed_p99_ms"] for s in clim["sectors"]}
    print("8-sector run matrix (dir deg -> input speed m/s):")
    for deg, name in zip(C.SECTORS, C.SECTOR_NAMES):
        print(f"  {name:>2} {deg:>3} deg  {speeds[name]:.1f} m/s")

    for deg, name in zip(C.SECTORS, C.SECTOR_NAMES):
        vel = run_sector(name, deg, speeds[name])
        multiplier_raster(name, vel, speeds[name])
    print("done")


if __name__ == "__main__":
    main()
