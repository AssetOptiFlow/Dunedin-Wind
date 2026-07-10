"""Fetch ERA5 hourly gust + 10 m wind for the bbox from the CDS.

Usage:
  python 03_fetch_era5.py --test          # single test year (config.ERA5_TEST_YEAR)
  python 03_fetch_era5.py --all           # full 1991-2020 pull (Checkpoint 2 first!)
  python 03_fetch_era5.py --year 1997     # one specific year

Requires ~/.cdsapirc (new CDS API format, two lines):
  url: https://cds.climate.copernicus.eu/api
  key: <personal-access-token>
The ERA5 licence must be accepted once at
https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels
(otherwise the first request returns 403).

Request chunking (all resumable via skip-if-exists):
- 3-variable year requests fail the CDS cost cap ("cost limits exceeded",
  observed 2026-07-10). Monthly 3-var chunks work but cost ~360 queue waits.
- 1-variable YEAR requests pass the cap (verified 2026-07-11), so incomplete
  years are fetched as 3 per-variable yearly files (era5_YYYY_<var>.nc) —
  4x fewer queue waits. Years already complete as monthly files are kept.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

RC = Path.home() / ".cdsapirc"


def check_rc():
    if not RC.exists():
        sys.exit(
            "BLOCKED: ~/.cdsapirc not found.\n"
            "Create it with exactly two lines:\n"
            "  url: https://cds.climate.copernicus.eu/api\n"
            "  key: <your CDS Personal Access Token>\n"
            "Token: https://cds.climate.copernicus.eu/profile\n"
            "Also accept the ERA5 licence once on the dataset page."
        )


def fetch_month(client, year: int, month: int, dest: Path) -> float:
    """Retrieve one month; returns elapsed seconds. Skips if file exists."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {year}-{month:02d}: exists "
              f"({dest.stat().st_size/1e6:.1f} MB), skipping", flush=True)
        return 0.0
    t0 = time.time()
    client.retrieve(
        C.ERA5_DATASET,
        {
            "product_type": ["reanalysis"],
            "variable": C.ERA5_VARIABLES,
            "year": [str(year)],
            "month": [f"{month:02d}"],
            "day": [f"{d:02d}" for d in range(1, 32)],
            "time": [f"{h:02d}:00" for h in range(24)],
            # N, W, S, E
            "area": [C.BBOX["north"], C.BBOX["west"],
                     C.BBOX["south"], C.BBOX["east"]],
            "grid": [0.25, 0.25],
            "data_format": "netcdf",
            "download_format": "unzipped",
        },
        str(dest),
    )
    dt = time.time() - t0
    print(f"  {year}-{month:02d}: {dest.stat().st_size/1e6:.2f} MB "
          f"in {dt:.0f} s", flush=True)
    return dt


VAR_TAGS = {"10m_wind_gust_since_previous_post_processing": "fg10",
            "10m_u_component_of_wind": "u10",
            "10m_v_component_of_wind": "v10"}


def fetch_year_var(client, year: int, variable: str, dest: Path) -> float:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {year} {VAR_TAGS[variable]}: exists, skipping", flush=True)
        return 0.0
    t0 = time.time()
    client.retrieve(
        C.ERA5_DATASET,
        {
            "product_type": ["reanalysis"],
            "variable": [variable],
            "year": [str(year)],
            "month": [f"{m:02d}" for m in range(1, 13)],
            "day": [f"{d:02d}" for d in range(1, 32)],
            "time": [f"{h:02d}:00" for h in range(24)],
            "area": [C.BBOX["north"], C.BBOX["west"],
                     C.BBOX["south"], C.BBOX["east"]],
            "grid": [0.25, 0.25],
            "data_format": "netcdf",
            "download_format": "unzipped",
        },
        str(dest),
    )
    dt = time.time() - t0
    print(f"  {year} {VAR_TAGS[variable]}: {dest.stat().st_size/1e6:.2f} MB "
          f"in {dt/60:.1f} min", flush=True)
    return dt


def fetch_year(client, year: int) -> float:
    monthly = [C.ERA5_DIR / f"era5_{year}_{m:02d}.nc" for m in range(1, 13)]
    yearly = [C.ERA5_DIR / f"era5_{year}_{VAR_TAGS[v]}.nc"
              for v in C.ERA5_VARIABLES]
    if all(f.exists() and f.stat().st_size > 0 for f in monthly):
        print(f"  {year}: complete (monthly), skipping", flush=True)
        return 0.0
    if all(f.exists() and f.stat().st_size > 0 for f in yearly):
        print(f"  {year}: complete (per-var yearly), skipping", flush=True)
        return 0.0
    # Mostly-complete monthly years: cheaper to finish the missing months
    # than to refetch the year per-variable.
    have = [f.exists() and f.stat().st_size > 0 for f in monthly]
    if sum(have) >= 10:
        return sum(fetch_month(client, year, m + 1, monthly[m])
                   for m in range(12) if not have[m])
    # Partial monthly files would duplicate times against the yearly files
    # in 04's combine — remove them before switching format for this year.
    for f in monthly:
        if f.exists():
            f.unlink()
    return sum(fetch_year_var(client, year, v, d)
               for v, d in zip(C.ERA5_VARIABLES, yearly))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--test", action="store_true")
    g.add_argument("--all", action="store_true")
    g.add_argument("--year", type=int)
    args = ap.parse_args()

    check_rc()
    import cdsapi
    client = cdsapi.Client()
    C.ERA5_DIR.mkdir(parents=True, exist_ok=True)

    if args.test:
        years = [C.ERA5_TEST_YEAR]
    elif args.year:
        years = [args.year]
    else:
        years = C.ERA5_YEARS

    total = 0.0
    for y in years:
        total += fetch_year(client, y)
    print(f"done: {len(years)} year(s), {total/60:.1f} min total")


if __name__ == "__main__":
    main()
