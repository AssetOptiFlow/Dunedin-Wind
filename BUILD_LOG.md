# BUILD_LOG

## 2026-07-10 — Session 1 addendum 2: generalised cartographic zones

**Goal.** Rework zone polygons into smooth, curved, council-wind-zone-map
style shapes (Jamie's reference: WCC wind zones via wellingtonista.com),
replacing the rectangular cell-edge polygons.

**Decisions.**
- Jamie explicitly wants the SHAPE/DESIGN of NZS 3604-style council maps
  only — NOT the NZS 3604 design-gust methodology (offered, declined for
  now; would need the 30-yr record for an extreme-value fit, still on hold).
- New zone derivation: 1 km Gaussian smooth of the gust field -> 5x upsample
  (100 m) -> nested cumulative thresholds at the class breaks (contour
  style, gap/overlap-free) -> drop islands/holes < 2 km^2 -> round-join
  buffer smoothing (250 m) -> difference into bands. Tunables in config.py.
- Breaks recomputed on the SMOOTHED field (raw-field breaks emptied Zone 5
  because smoothing compresses the tails). Raw + smoothed break sets both in
  outputs/diagnostics/zone_breaks_smoothed.json.
- Zones clipped to land, council-map style (water unzoned; continuous raster
  still covers it). Ocean mask = low cells connected to the map edge (flood
  fill) — a plain elevation cut wrongly dropped the below-sea-level drained
  Taieri Plain; caught on the screenshot, fixed same session.
- Webmap default layers now zones+arrows+stations (gust raster opt-in).

**Residuals & caveats.**
- The zone layer is now explicitly GENERALISED CARTOGRAPHY: 1 km smoothing
  compresses zone value ranges to 1-2 km/h widths (69-73 ... 78-82 km/h) —
  zones are ordinal exposure classes, not precise bins. Stated in each
  feature's note property. Quantitative values live in the continuous layer.
- Zone areas: 90 / 298 / 601 / 586 / 159 km^2 (Zones 1-5).

**Checkpoints.** None new; Checkpoint 5's Jenks choice carried over (applied
to the smoothed field). NZS 3604 design-gust variant parked with the 30-yr
pull decision.

**Next.** Unchanged: 30-yr pull on Jamie's go, then re-run 04->10.

## 2026-07-10 — Session 1 addendum: repo push, km/h display, zone clustering

**Goal.** Publish to GitHub; convert user-facing units to km/h; normalise
zone speckle into connected clusters (both requested by Jamie).

**Decisions.**
- Pushed to https://github.com/AssetOptiFlow/Dunedin-Wind (branch `main`).
- Units: rasters and GeoJSON keep m/s (SI, matches AS/NZS and the science);
  all display (legend, zone labels/popups, arrow popups) is km/h; vectors
  carry both attributes (`gust_range_ms`/`gust_range_kmh`, `speed_ms`/`speed_kmh`).
- Zone clustering: 3x3 strict-majority smooth (1 pass, nodata-aware) then
  rasterio sieve of patches < 8 cells (2 km^2, `ZONE_MIN_PATCH_CELLS` in
  config) into the surrounding zone, before polygonising.

**Residuals & caveats.**
- Cleanup trades extreme-cell fidelity for legibility: Zone 5 shrank
  283 -> 159 cells, Zone 1 348 -> 238 (isolated extremes absorbed into
  neighbours). The continuous gust raster retains full 500 m detail, so no
  information is lost from the product — only from the zone abstraction.
- Zone 4 still has 75 patches (12-75 across zones); it is a genuinely
  scattered "ridge flank" class. Sieving harder starts deleting real
  structure; threshold left tunable.

**Checkpoints.** None (display/presentation changes only; classification
scheme and breaks unchanged from Checkpoint 5).

**Next.** Unchanged: Jamie reviews webmap; 30-yr pull on his go.

## 2026-07-10 — Session 1: full pipeline stood up, 2005 shakedown webmap

**Goal.** Stand up the toolchain on a clean Windows 11 machine and run the
entire pipeline end-to-end for the Dunedin trial. Outcome: complete, with the
climatology provisionally based on the 2005 test year (see Checkpoint 2).

**Decisions.**
- Environment in the brief (conda `windzone`, WindNinja on PATH, `~/.cdsapirc`)
  did not exist; Jamie confirmed a fresh install of the full stack.
- `BUILD_LOG_convention.md` drafted fresh (Jamie confirmed); CliFlo public
  station metadata only, no account (Jamie confirmed).
- DEM: Copernicus GLO-30 (anonymous AWS) instead of SRTM — `elevation` pkg
  needs GNU make/curl, OpenTopography needs an API key. GLO-30 is a DSM
  (canopy/buildings), arguably right for wind exposure. **Checkpoint 1:
  accepted by Jamie.**
- ERA5: new CDS rejects year-sized hourly netcdf requests ("cost limits
  exceeded"), so fetch is chunked per month with skip-if-exists resume.
  Deliveries are "as_source" zips (gust in forecast stream, u/v in analysis
  stream — two netCDF members each); climatology unpacks transparently.
  Measured test year (2005): 12 requests, 38.5 min, 2.4 MB. Extrapolated
  30-yr pull: ~360 requests, ~19-20 h queue time, ~72 MB, $0.
  **Checkpoint 2: Jamie chose HOLD — build everything on 2005 first, review
  the webmap, then decide the 30-yr pull.** All 2005-derived numbers below
  are therefore provisional.
- WindNinja: `domainAverageInitialization`, non-diurnal, mass-conserving
  solver, 200 m mesh -> 500 m ASCII output (this win64 build has no GeoTIFF
  writer — `--help`/`--runtime_options` captured in outputs/diagnostics/).
  8 sectors at per-sector p99 10 m speed (N 9.0, NE 11.4, E 8.8, SE 8.5,
  S 10.7, SW 14.2, W 13.1, NW 7.5 m/s). **Checkpoint 3: confirmed by Jamie.**
- Confidence: 3 stations (Dunedin Aerodrome AWS, Musselburgh EWS, Taiaroa
  Head), distance bands 7.5/15 km, TRI terciles computed over LAND cells only
  (ocean TRI=0 degenerated the lower break to 0.0 — fixed same session),
  weakest-link min(). **Checkpoint 4: confirmed by Jamie.**
- Zones: gust distribution strongly peaked at ~21.4 m/s; quantile breaks
  collapse zones 2-4 into 0.7 m/s. **Checkpoint 5: Jenks chosen by Jamie.**
  Breaks: 13.2 / 19.2 / 20.8 / 21.9 / 23.2 / 26.8 m/s.
- Arrows: **Checkpoint 6: 2.5 km spacing confirmed** (450 points). Dominant
  sector per cell = argmax of (top-decile-gust sector weight x local
  multiplier x sector p99 gust); arrows drawn pointing downwind.
- Webmap: single self-contained index.html (0.7 MB) — Leaflet inlined,
  rasters as base64 PNG overlays, vectors inline; only network dependency is
  OSM basemap tiles. Verified in headless Edge (DOM probes + screenshot).

**Provenance.**
- Miniconda (repo.anaconda.com, 130,747,768 B, 2026-07-10) -> %USERPROFILE%\miniconda3.
- WindNinja 3.12.2 win64 (research.fs.usda.gov, 99,636,043 B, 2026-07-10)
  -> C:\WindNinja\WindNinja-3.12.2.
- conda env `windzone`: conda-forge, python 3.12, rasterio 1.5.0, richdem
  2.4.3, whitebox, geopandas, xarray, netcdf4, cdsapi, scipy, pandas, jenkspy,
  pillow, matplotlib (spec: environment.yml).
- Copernicus GLO-30 DSM: 4 tiles (S46/S47 x E169/E170), anonymous S3
  copernicus-dem-30m, 2026-07-10. ESA licence. Merged/clipped/warped to
  EPSG:32759 @ 30 m, bbox + 5 km buffer; elev -33..895 m (small coastal
  negatives are GLO-30 ocean noise).
- ERA5 hourly 2005 (fg10, u10, v10), CDS reanalysis-era5-single-levels,
  retrieved 2026-07-10, Copernicus licence. 70,080 samples; p99 gust
  20.3 m/s; SW+W = 81.6% of top-decile gust hours.
- Station coordinates: public NIWA/CliFlo metadata, approximate to ~100 m,
  recorded in webmap/stations.geojson. Locations only — no gust records used.

**Residuals & caveats.**
- Climatology is ONE YEAR (2005). Sector speeds, p99 gust, zone breaks and
  arrows will all shift with the 30-year record; the pipeline re-runs
  scripts 04-10 unchanged when it lands.
- Gust surface 13.0-28.7 m/s (mean 21.2), worst-case max 33.6 — below the
  ~45 m/s southern-NZ design gust (sanity OK). Max/min spatial ratio 2.22
  vs ~1.8 credible AS/NZS terrain-multiplier spread: slightly wide, driven
  by flat offshore minima; kept, documented (outputs/diagnostics/asnzs_sanity.md).
- ERA5 resolves the domain with ~12 grid points; all fine structure is
  modelled terrain response, not observation.
- Mass-conserving solver in complex terrain (peninsula lee): captured only
  via the TRI confidence term. NinjaFOAM sensitivity run = future work.
- 41% of cells are >15 km from any station (max 32 km, western inland) —
  flagged low confidence / no_station_within_threshold. Honest, not a bug.
- environment.yml pins python only; export a lockfile before scaling to Otago.

**Checkpoints.** 1 accepted (GLO-30); 2 HOLD (2005-only shakedown; 30-yr pull
deferred pending webmap review — ~20 h unattended when approved); 3 confirmed;
4 confirmed (3 stations, 7.5/15 km); 5 Jenks; 6 2.5 km.

**Next.** Jamie reviews webmap/index.html. If approved: run the 30-yr pull
(`03_fetch_era5.py --all`, resumable), then re-run 04→10. Then consider
GitHub remote + Pages deploy, and the Otago-scale plan.
