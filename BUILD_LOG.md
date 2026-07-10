# BUILD_LOG

## 2026-07-10 — Session 1: environment + repo scaffold

**Goal.** Stand up the full toolchain on a clean Windows 11 machine and
scaffold the repo for the Dunedin wind gust screening trial.

**Decisions.**
- The environment described in the brief (conda `windzone` env, WindNinja on
  PATH, `~/.cdsapirc`) did not exist on this machine. Jamie confirmed: install
  the full stack fresh; he will supply the CDS token when the pipeline asks.
- `BUILD_LOG_convention.md` did not exist anywhere; Jamie confirmed drafting it
  fresh (this file follows it).
- CliFlo: no account will be used — public station metadata only. Confirmed by
  Jamie; sufficient because the confidence layer needs station *locations*, not
  gust records.
- DEM: Copernicus GLO-30 via anonymous AWS S3 instead of SRTM. Reason: the
  `elevation` package requires GNU make/curl (unreliable on Windows) and
  OpenTopography now requires an API key. GLO-30 is a DSM (canopy/buildings
  included) vs SRTM quasi-DTM — arguably preferable for wind exposure.
  **Pending Jamie's sign-off at Checkpoint 1**; fallback is SRTMGL1 via a free
  OpenTopography key.
- WindNinja initialization: `domainAverageInitialization`, non-diurnal,
  mass-conserving solver (`momentum_flag=false`) — verified against the shipped
  `cli_domainAverage.cfg`, `cli.cpp`, and the installed CLI's own `--help`.
  Awaiting Jamie's confirmation at Checkpoint 3 before runs.
- The 3.12.2 win64 build exposes **no GeoTIFF output option** (`--help` and
  `--runtime_options` captured in `outputs/diagnostics/`). Using ASCII AAIGRID
  output (`_vel.asc`/`_ang.asc`) at 500 m instead; rasterio reads these
  natively. This was the planned fallback.
- Python 3.12 (not 3.13) in the env for binary-wheel maturity; richdem 2.4.3
  has conda-forge win-64 builds and imports cleanly.

**Provenance.**
- Miniconda: https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
  (130,747,768 bytes, retrieved 2026-07-10), installed to `%USERPROFILE%\miniconda3`,
  user-level, not on PATH.
- WindNinja 3.12.2 win64: https://research.fs.usda.gov/sites/default/files/2026-03/firelab-windninja-3.12.2-win64.zip
  (99,636,043 bytes, retrieved 2026-07-10), installed to
  `C:\WindNinja\WindNinja-3.12.2` (NSIS silent). `WindNinja_cli.exe --help`
  runs; full option dump in `outputs/diagnostics/windninja_cli_help.txt`.
- conda env `windzone`: conda-forge, python=3.12, rasterio 1.5.0, richdem,
  whitebox, geopandas, xarray, netcdf4, cdsapi, scipy, pandas, jenkspy, pillow,
  matplotlib. All imports verified. Exact spec in `environment.yml`.

**Residuals & caveats.**
- WindNinja binaries are installed but no simulation has been run yet — the
  real smoke test is the first sector run in Phase 3.
- `environment.yml` pins only python; a `conda env export` lockfile should be
  captured once the pipeline has run end-to-end.

**Checkpoints.** None hit yet. Pending: 1 (terrain + DEM substitution),
2 (30-yr ERA5 cost), 3 (WindNinja run matrix), 4 (stations + distance
threshold), 5 (Jenks vs quantiles), 6 (arrow spacing).

**Next.** Phase 1: fetch GLO-30 tiles, build terrain layers, produce
quicklooks for Checkpoint 1.
