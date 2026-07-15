"""Per-year gust exposure surfaces for the year-comparison webmap.

For every complete calendar year of ERA5 on disk (both domains, ANY year —
not limited to config.ERA5_YEARS), applies the script-06 method with
year-local inputs:

  gust99_y(cell) = sum_s w_{s,y} * mult_s(cell) * era5_gust99_{s,y}

where w_{s,y} = sector frequency among that YEAR's top-decile gust hours and
era5_gust99_{s,y} = that year's per-sector p99 gust. The WindNinja
multipliers mult_s are climatological (terrain response per direction); all
interannual variation comes from ERA5. This keeps every yearly surface
method-identical to the headline 1991-2020 product.

File-driven over both domains (like 13); does NOT touch existing outputs.
Writes outputs_compare/<domain>/gust99_<year>_500m[_wgs84].tif (skip-if-
exists) + outputs_compare/yearly_stats.json (always rewritten).
Run 15_compare_map.py afterwards to rebuild the webmap.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

REPO = C.REPO
OUT = REPO / "outputs_compare"
DOMAINS = [
    {"key": "dunedin", "title": "Dunedin",
     "era5": REPO / "data" / "era5", "out": REPO / "outputs"},
    {"key": "central", "title": "Central Otago/Queenstown",
     "era5": REPO / "data_central" / "era5", "out": REPO / "outputs_central"},
]
CLIP_BUFFER_M = 10_000  # matches 13_combined_map


def complete_years(era5_dir):
    """Map year -> file list, for every year with 12 monthly files or 3
    per-variable yearly files. Partial years never enter (seasonal bias)."""
    years = sorted({int(m.group(1)) for f in era5_dir.glob("era5_*.nc")
                    if (m := re.match(r"era5_(\d{4})_", f.name))})
    out = {}
    for year in years:
        monthly = [era5_dir / f"era5_{year}_{m:02d}.nc" for m in range(1, 13)]
        yearly = [era5_dir / f"era5_{year}_{t}.nc" for t in ("fg10", "u10", "v10")]
        for candidate in (monthly, yearly):
            if all(f.exists() and f.stat().st_size > 0 for f in candidate):
                out[year] = candidate
                break
        else:
            print(f"  skipping incomplete year {year}")
    return out


def unpack_paths(era5_dir, files):
    """CDS multi-variable deliveries are zips (two streams); unpack into the
    same cache dir script 04 uses."""
    unpack = era5_dir / "unpacked"
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


def load_year(era5_dir, files):
    """Return flattened finite (u, v, gust) samples for one year."""
    parts = []
    for p in unpack_paths(era5_dir, files):
        with xr.open_dataset(p) as d:
            d = d.drop_vars([v for v in ("expver", "number") if v in d.variables])
            parts.append(d.load())
    ds = xr.combine_by_coords(parts, combine_attrs="drop_conflicts")
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    gust_name = "fg10" if "fg10" in ds else "i10fg"
    u = ds["u10"].values.ravel()
    v = ds["v10"].values.ravel()
    g = ds[gust_name].values.ravel()
    ds.close()
    ok = np.isfinite(u) & np.isfinite(v) & np.isfinite(g)
    return u[ok], v[ok], g[ok]


def year_sector_stats(u, v, g):
    """Per-sector p99 gust + top-decile-gust sector weights, year-local
    (same definitions as script 04)."""
    direction = (180 + np.rad2deg(np.arctan2(u, v))) % 360
    sector_idx = (np.round(direction / 45).astype(int)) % 8
    top_decile = g >= np.percentile(g, 90)
    g99, w = np.zeros(8), np.zeros(8)
    for i in range(8):
        m = sector_idx == i
        # A sector empty at p99 level in a single year gets zero weight; its
        # multiplier then never contributes for that year.
        g99[i] = np.percentile(g[m], C.GUST_PERCENTILE) if m.any() else 0.0
        w[i] = (m & top_decile).sum() / top_decile.sum()
    return g99, w / w.sum()


def service_clip_mask(profile):
    """True inside the Aurora service area + buffer, on the given UTM grid."""
    import geopandas as gpd
    g = gpd.read_file(C.SHARED_DATA / "substations" /
                      "aurora_zone_substations.geojson")
    g = g[g.geometry.geom_type == "Polygon"].to_crs(C.CRS_WORKING)
    clip = g.union_all().buffer(CLIP_BUFFER_M)
    return ~geometry_mask([clip], out_shape=(profile["height"], profile["width"]),
                          transform=profile["transform"], invert=False,
                          all_touched=True)


def main():
    from _util import reproject_to_wgs84
    stats = {"percentile": C.GUST_PERCENTILE,
             "method": "per-year ERA5 sector p99 x climatological WindNinja "
                       "multipliers (script-06 formula, year-local weights)",
             "clip": f"Aurora service area + {CLIP_BUFFER_M/1000:.0f} km",
             "domains": {}}

    for d in DOMAINS:
        print(f"=== {d['title']}")
        dom_out = OUT / d["key"]
        dom_out.mkdir(parents=True, exist_ok=True)

        mults, prof = [], None
        for name in C.SECTOR_NAMES:
            with rasterio.open(d["out"] / "windninja" / f"mult_{name}.tif") as src:
                mults.append(src.read(1))
                prof = prof or src.profile.copy()
        mults = np.stack(mults)
        prof.update(dtype="float32")
        clip_mask = service_clip_mask(prof)

        years = complete_years(d["era5"])
        dom = {"title": d["title"], "years": {}}
        for year, files in sorted(years.items()):
            utm = dom_out / f"gust99_{year}_500m.tif"
            wgs = dom_out / f"gust99_{year}_500m_wgs84.tif"
            if utm.exists() and wgs.exists():
                with rasterio.open(utm) as src:
                    surface = src.read(1)
                n = None  # not recomputed for cached years
                print(f"  {year}: cached")
            else:
                u, v, g = load_year(d["era5"], files)
                n = int(g.size)
                g99, w = year_sector_stats(u, v, g)
                surface = np.einsum("s,shw->hw", w * g99, mults).astype("float32")
                with rasterio.open(utm, "w", **prof) as dst:
                    dst.write(surface, 1)
                reproject_to_wgs84(utm, wgs)
                print(f"  {year}: {n:,} samples, clip mean "
                      f"{np.nanmean(surface[clip_mask]):.1f} m/s")
            inside = surface[clip_mask & np.isfinite(surface)]
            y = {"clip_mean_ms": round(float(inside.mean()), 3),
                 "clip_max_ms": round(float(inside.max()), 2),
                 "clip_cells": int(inside.size)}
            if n:
                y["n_samples"] = n
            dom["years"][str(year)] = y
        stats["domains"][d["key"]] = dom

    OUT.mkdir(exist_ok=True)
    path = OUT / "yearly_stats.json"
    path.write_text(json.dumps(stats, indent=1))
    for k, dom in stats["domains"].items():
        ys = sorted(dom["years"])
        print(f"{k}: {len(ys)} years ({ys[0]}-{ys[-1]})")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
