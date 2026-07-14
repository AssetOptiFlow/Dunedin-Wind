"""Build the ERA5 gust/wind climatology from the downloaded years.

Domain-level (all grid points pooled — consistent with the domain-average
WindNinja design; the bbox spans only ~8-12 ERA5 cells):

  - overall 99th-percentile gust (10fg)
  - per-sector (8 x 45 deg, wind FROM): hour frequency, 99th-pct gust,
    99th-pct 10 m mean speed (WindNinja input_speed),
  - sector frequencies among top-decile gust hours (weights for script 06).

Writes outputs/era5_climatology.json + a distribution diagnostic PNG.
"""
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C


def complete_year_files():
    """Only complete years enter the climatology: 12 monthly files OR 3
    per-variable yearly files. Partial years (mid-download) would bias the
    seasonal mix."""
    files, skipped = [], []
    for year in C.ERA5_YEARS:
        monthly = [C.ERA5_DIR / f"era5_{year}_{m:02d}.nc" for m in range(1, 13)]
        yearly = [C.ERA5_DIR / f"era5_{year}_{t}.nc"
                  for t in ("fg10", "u10", "v10")]
        for candidate in (monthly, yearly):
            if all(f.exists() and f.stat().st_size > 0 for f in candidate):
                files.extend(candidate)
                break
        else:
            if any(f.exists() for f in monthly + yearly):
                skipped.append(year)
    if skipped:
        print(f"skipping incomplete year(s): {skipped}")
    return sorted(files)


def unpack_paths(files):
    """The CDS delivers "as_source" zips for multi-stream (multi-variable)
    requests (gust = forecast stream, u/v = analysis stream -> two netCDFs
    per month); single-variable deliveries are plain netCDF. Unpack zips
    transparently, cache in era5/unpacked/."""
    import zipfile
    unpack = C.ERA5_DIR / "unpacked"
    unpack.mkdir(exist_ok=True)
    paths = []
    for f in files:
        with open(f, "rb") as fh:
            is_zip = fh.read(2) == b"PK"
        if not is_zip:
            paths.append(f)
            continue
        with zipfile.ZipFile(f) as z:
            for m in z.namelist():
                if not m.endswith(".nc"):
                    continue
                dest = unpack / f"{f.stem}_{Path(m).name}"
                if not dest.exists():
                    dest.write_bytes(z.read(m))
                paths.append(dest)
    return paths


def iter_samples():
    """Yield per-year flattened (u, v, gust) sample arrays.

    Deliberately never combines all years into one xarray Dataset:
    combine_by_coords over ~90 datasets crashed natively (exit 0xC06D007F,
    2026-07-14) on the larger central domain. Per-year merges are small and
    keep peak memory flat."""
    files = complete_year_files()
    if not files:
        sys.exit("no complete ERA5 years — run 03_fetch_era5.py first")
    by_year = {}
    for p in unpack_paths(files):
        year = int(p.name.split("_")[1])
        by_year.setdefault(year, []).append(p)

    for year in sorted(by_year):
        parts = []
        for p in by_year[year]:
            with xr.open_dataset(p) as d:
                d = d.drop_vars([v for v in ("expver", "number")
                                 if v in d.variables])
                parts.append(d.load())
        ds = xr.combine_by_coords(parts, combine_attrs="drop_conflicts")
        if "valid_time" in ds.dims:
            ds = ds.rename({"valid_time": "time"})
        gust_name = "fg10" if "fg10" in ds else "i10fg"
        yield (year, gust_name, ds["u10"].values.ravel(),
               ds["v10"].values.ravel(), ds[gust_name].values.ravel())
        ds.close()


def main():
    us, vs, gs = [], [], []
    gust_name = None
    years_loaded = []
    for year, gname, u, v, g in iter_samples():
        gust_name = gname
        years_loaded.append(year)
        us.append(u); vs.append(v); gs.append(g)
    print(f"loaded {len(years_loaded)} years "
          f"({years_loaded[0]}-{years_loaded[-1]})")
    u = np.concatenate(us); v = np.concatenate(vs); g = np.concatenate(gs)
    del us, vs, gs
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(g)
    u, v, g = u[ok], v[ok], g[ok]
    n = g.size
    print(f"{n:,} finite (hour, gridpoint) samples, gust var '{gust_name}'")

    speed = np.hypot(u, v)
    # Meteorological wind-FROM direction.
    direction = (180 + np.rad2deg(np.arctan2(u, v))) % 360
    sector_idx = (np.round(direction / 45).astype(int)) % 8

    q = C.GUST_PERCENTILE
    gust99_overall = float(np.percentile(g, q))

    top_decile = g >= np.percentile(g, 90)
    sectors = []
    for i, (deg, name) in enumerate(zip(C.SECTORS, C.SECTOR_NAMES)):
        m = sector_idx == i
        sectors.append({
            "sector": name,
            "center_deg": deg,
            "freq": float(m.mean()),
            "freq_top_decile_gust": float((m & top_decile).sum() / top_decile.sum()),
            "gust_p99_ms": float(np.percentile(g[m], q)) if m.any() else None,
            "speed_p99_ms": float(np.percentile(speed[m], q)) if m.any() else None,
        })

    out = {
        "source": "ERA5 reanalysis-era5-single-levels, hourly",
        "gust_variable": gust_name,
        "years": sorted({int(f.stem.split("_")[1])
                         for f in complete_year_files()}),
        "bbox": C.BBOX,
        "n_samples": int(n),
        "percentile": q,
        "gust_p99_overall_ms": gust99_overall,
        "speed_p99_overall_ms": float(np.percentile(speed, q)),
        "sectors": sectors,
    }
    C.OUTPUTS.mkdir(exist_ok=True)
    path = C.OUTPUTS / "era5_climatology.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

    # Diagnostics: gust histogram + sector rose numbers.
    C.DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].hist(g, bins=80, color="#43708a")
    axes[0].axvline(gust99_overall, color="crimson",
                    label=f"p{q} = {gust99_overall:.1f} m/s")
    axes[0].set_xlabel("hourly max gust (m/s)")
    axes[0].set_title("ERA5 gust distribution (all hours x gridpoints)")
    axes[0].legend()
    theta = np.deg2rad(C.SECTORS)
    freqs = [s["freq_top_decile_gust"] for s in sectors]
    ax = plt.subplot(122, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.bar(theta, freqs, width=np.deg2rad(40), color="#c2571a", alpha=0.8)
    ax.set_title("Sector frequency among top-decile gust hours")
    fig.savefig(C.DIAGNOSTICS / "era5_climatology.png", dpi=120,
                bbox_inches="tight")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
