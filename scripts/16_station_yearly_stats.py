"""Per-station, per-year ERA5 gust statistics for the year-comparison webmap.

For each station in webmap*/stations.geojson, extracts the hourly ERA5 series
at the NEAREST 0.25-degree grid cell (~25 km) and computes, per calendar
year: annual max gust (+ NZST date), mean daily-max gust, p99 hourly gust,
mean hourly gust, counts of days with daily max >= 90 / 120 km/h, and the
sector distribution of strong-gust hours (>= the station's own all-years p90,
a FIXED threshold so roses are comparable across years).

These are MODEL values at grid scale — not station observations (the project
deliberately uses no CliFlo gust records). Days are NZST (UTC+12, no DST).

Writes outputs_compare/station_yearly_stats.json.
Run after new years are fetched; rerun 15_compare_map.py afterwards.
"""
import json
import sys
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import config as C

m14 = import_module("14_yearly_gust")

REPO = C.REPO
OUT = REPO / "outputs_compare"
DOMAINS = [
    {"key": "dunedin", "title": "Dunedin", "era5": REPO / "data" / "era5",
     "stations": REPO / "webmap" / "stations.geojson"},
    {"key": "central", "title": "Central Otago/Queenstown",
     "era5": REPO / "data_central" / "era5",
     "stations": REPO / "webmap_central" / "stations.geojson"},
]
D90_MS, D120_MS = 90 / 3.6, 120 / 3.6


def open_year(era5_dir, files):
    parts = []
    for p in m14.unpack_paths(era5_dir, files):
        with xr.open_dataset(p) as d:
            d = d.drop_vars([v for v in ("expver", "number") if v in d.variables])
            parts.append(d.load())
    ds = xr.combine_by_coords(parts, combine_attrs="drop_conflicts")
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    return ds


def main():
    stations = []
    for dom in DOMAINS:
        feats = json.loads(dom["stations"].read_text())["features"]
        years = m14.complete_years(dom["era5"])
        print(f"=== {dom['title']}: {len(feats)} stations, {len(years)} years")

        # series[station_name][year] = (times_nzst, gust, sector_idx)
        series = {f["properties"]["name"]: {} for f in feats}
        grid_pt = {}
        for year, files in sorted(years.items()):
            ds = open_year(dom["era5"], files)
            gust_name = "fg10" if "fg10" in ds else "i10fg"
            for f in feats:
                lon, lat = f["geometry"]["coordinates"]
                cell = ds.sel(latitude=lat, longitude=lon, method="nearest")
                name = f["properties"]["name"]
                grid_pt[name] = (float(cell.latitude), float(cell.longitude))
                g = cell[gust_name].values.astype("float32")
                u, v = cell["u10"].values, cell["v10"].values
                direction = (180 + np.rad2deg(np.arctan2(u, v))) % 360
                sector = (np.round(direction / 45).astype("int8")) % 8
                t = pd.to_datetime(ds.time.values) + pd.Timedelta(hours=12)
                ok = np.isfinite(g)
                series[name][year] = (t[ok], g[ok], sector[ok])
            ds.close()
            print(f"  {year}: extracted", flush=True)

        for f in feats:
            name = f["properties"]["name"]
            lon, lat = f["geometry"]["coordinates"]
            all_g = np.concatenate([series[name][y][1] for y in sorted(years)])
            p90 = float(np.percentile(all_g, 90))
            st = {"name": name, "domain": dom["title"], "lat": lat, "lon": lon,
                  "grid_lat": grid_pt[name][0], "grid_lon": grid_pt[name][1],
                  "strong_thr_ms": round(p90, 2), "years": {}}
            for year in sorted(years):
                t, g, sec = series[name][year]
                dmax = pd.Series(g, index=t).groupby(t.date).max()
                strong = g >= p90
                n_strong = int(strong.sum())
                rose = [round(float((sec[strong] == i).sum() / max(n_strong, 1)), 4)
                        for i in range(8)]
                st["years"][str(year)] = {
                    "max_ms": round(float(g.max()), 2),
                    "max_date": t[int(np.argmax(g))].date().isoformat(),
                    "mdm_ms": round(float(dmax.mean()), 3),
                    "p99_ms": round(float(np.percentile(g, 99)), 2),
                    "mean_ms": round(float(g.mean()), 3),
                    "d90": int((dmax >= D90_MS).sum()),
                    "d120": int((dmax >= D120_MS).sum()),
                    "rose": rose,
                }
            stations.append(st)
            yrs = st["years"]
            worst = max(yrs, key=lambda y: yrs[y]["max_ms"])
            print(f"  {name}: grid cell ({st['grid_lat']:.2f}, "
                  f"{st['grid_lon']:.2f}), record max "
                  f"{yrs[worst]['max_ms']*3.6:.0f} km/h ({worst})")

    out = {
        "note": ("ERA5 model values at each station's nearest 0.25-deg grid "
                 "cell (~25 km) — NOT station observations. Days are NZST "
                 "(UTC+12, no DST). Rose = sector share of hours >= the "
                 "station's all-years p90 gust (fixed threshold)."),
        "sectors": C.SECTOR_NAMES,
        "stations": stations,
    }
    path = OUT / "station_yearly_stats.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"wrote {path} ({path.stat().st_size/1e3:.0f} kB)")


if __name__ == "__main__":
    main()
