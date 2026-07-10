# Dunedin-Wind

First-pass **wind gust exposure screening map** for the Dunedin region, NZ
(bbox −46.1, 170.0 → −45.7, 170.8 WGS84) at 500 m resolution — a trial before
scaling to full Otago.

> **This is a screening tool, not a validated measurement product.**
> Modelled screening estimate (ERA5 + WindNinja terrain adjustment). Not a
> validated measurement; do not use for engineering design. No wind zone
> records exist for this network; every output carries an explicit confidence
> layer, and its weaknesses are logged in `BUILD_LOG.md`.

## Method (summary)

1. Copernicus GLO-30 DEM → slope, aspect, TRI, 8-sector directional exposure.
2. ERA5 hourly gust + 10 m wind climatology, 1991–2020.
3. WindNinja (mass-conserving, `domainAverageInitialization`, non-diurnal)
   8-sector runs at the per-sector 99th-percentile 10 m speed → terrain
   speed-up multipliers on a 500 m grid.
4. Gust surface = sector-frequency-weighted (gust-bearing hours) multiplier ×
   ERA5 99th-percentile gust. AS/NZS 1170.2 gust factors used only as a
   plausibility bound, never for classification.
5. Confidence layer (high/medium/low): distance to nearest usable station,
   terrain complexity (TRI), explicit no-station flag.
6. 5 exposure zones (Zone 1 lowest … Zone 5 highest), polygonised.
7. Dominant gust-direction arrows on a ~2.5 km grid.
8. Self-contained Leaflet webmap (`webmap/index.html`) — 4 toggleable layers +
   combined legend. Only network dependency is the OSM basemap tiles.

## Known uncertainty drivers (deliberate, documented)

- ERA5 resolves the domain with only ~8–12 grid points; all fine spatial
  structure comes from the terrain model, not observations.
- WindNinja's mass-conserving solver degrades in very complex terrain
  (peninsula lee effects) — captured by the TRI term of the confidence layer.
- GLO-30 is a surface model (includes canopy/buildings), not bare earth.
- No station validation has been performed; station distance only bounds
  confidence, it does not calibrate the estimate.

## Running

```
conda env create -f environment.yml   # or see BUILD_LOG for exact install
conda run -n windzone python scripts/01_fetch_dem.py
...
conda run -n windzone python scripts/10_build_webmap.py
```

Scripts are numbered and idempotent; each writes to `data/` (gitignored) or
`outputs/`. Script 03 requires a CDS Personal Access Token
(https://cds.climate.copernicus.eu/) and pauses to ask for it if
`~/.cdsapirc` is missing. WindNinja 3.12.2 is expected at the path in
`config.py`.

See `BUILD_LOG_convention.md` / `BUILD_LOG.md` for the full decision record.
