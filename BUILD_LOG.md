# BUILD_LOG

## 2026-07-12 — Session 4: historical lightning layer (code ready, awaiting data export)

**Goal.** Add a historical lightning strike layer for the bbox (Jamie's ask).

**Decisions.**
- Source research (verified live): NZLDN point data is commercial-only
  (Transpower-owned, MetService-exclusive; 2023 OIA refused). The open,
  authoritative option is MfE layer 52851 "Lightning strike density,
  2000-14" — NZLDN-derived, 5 km cells, EPSG:2193, strikes per 25 km^2
  cell/yr, CC BY 3.0 NZ. Jamie chose: build this now; park point data
  (MetService extract, or WWLLN archive — Otago Uni hosts a station).
  Blitzortung ruled out: terms prohibit risk-analysis use. No geostationary
  lightning coverage at -46°.
- Resolution honesty: coastal Otago ~0.02-0.08 CG strikes/km^2/yr → ~10-30
  strikes per 5 km cell over the 15-yr record → 5 km is the finest
  defensible grid; NOT resampled to the 500 m analysis grid. Jamie chose
  Gaussian display smoothing with the 5 km provenance stated in the legend;
  the honest nearest-neighbour 5 km GeoTIFF ships alongside.
- Script 11 gates on a user action (free MfE/Koordinates account + GeoTIFF
  export) exactly like script 03's CDS gate, and self-skips (exit 0) so
  full_refresh.py never blocks on this optional layer. Webmap injects the
  layer + legend section (Blues ramp, CC-BY attribution — a licence
  requirement) only when outputs exist; a commented slot is left for a
  future strike-points layer.

**Provenance.** No real data ingested yet. Code path verified end-to-end
with a synthetic 5 km EPSG:2193 raster (deleted after test, never committed);
gate/skip behaviour and clean webmap rebuild without the layer both verified.

**Residuals & caveats.**
- The MfE record is 2000-14 — it will not match the wind layers' 1991-2020
  window; period stated in layer name and legend.
- Density says nothing about individual strikes; strike-vs-fault correlation
  needs the parked point-data path.
- Headless-Edge visual verification deferred (Edge headless wedged
  system-wide this session, even on about:blank); HTML verified statically.
  Screenshot check to run when Edge recovers / after real data lands.

**Checkpoints.** Source choice + display smoothing confirmed by Jamie
(2026-07-12). Awaiting: his MfE export to activate the layer.

**Next.** Jamie exports layer 52851 GeoTIFF (EPSG:2193) to
data/lightning/lightning_density_2000_14.tif → rerun scripts 11 + 10 →
visual check → commit refreshed webmap.

## 2026-07-12 — Session 3: full 30-year product

**Goal.** Complete the 1991-2020 pull and rebuild everything on the full
climatological normal.

**Decisions / events.**
- Pull completed 04:33 (all 225 files: 180 monthly 1991-2005 + 45
  per-variable yearly 2006-2020). Total ERA5 payload ~180 MB raw.
- The automatic post-pull refresh crashed at the climatology step 8 s after
  the last download (native crash, transient — most likely a file-flush race
  on the final netCDF). Manual rerun succeeded unchanged. If this recurs,
  add a settle delay between steps in full_refresh.py.
- Zip-validation false alarm: single-variable CDS deliveries are PLAIN
  netCDF (HDF5 magic), not zips — only multi-stream (multi-variable)
  requests get zip-wrapped. Script 04 already handles both via magic bytes.
- WindNinja speed-aware cache behaved as designed: 5 sectors re-ran with
  changed 30-yr speeds, 3 (NE, SE, W) skipped within the 0.05 m/s tolerance.

**Provenance.** ERA5 hourly 1991-2020 (fg10, u10, v10), CDS
reanalysis-era5-single-levels, retrieved 2026-07-10..12, Copernicus licence.
2,103,936 samples across 8 grid points x 30 years.

**Results (30-yr, vs 14-yr interim / 2005-only).**
- Domain p99 gust 22.3 m/s (22.0 / 20.3). W+SW = 84% of top-decile gust
  hours (81% / 82%) — the southwesterly regime is stable across records.
- Gust surface 13.8-31.2 m/s, mean 23.0; worst-case max 35.5 — below the
  ~45 m/s design gust; max/min ratio 2.26 (offshore minima, as before).
- Zone breaks (smoothed field): 20.6/22.1/22.6/23.0/23.5/24.7 m/s
  (74-89 km/h). Zone areas 103/305/603/576/147 km^2. Geometry consistent
  with the interim map — the record length shifts levels (~+0.3 m/s over
  the 14-yr interim) far more than shapes.
- Legend now reads "ERA5 1991-2020" (interim tag auto-cleared).

**Residuals & caveats.** All prior residuals stand (ERA5 coarseness, solver
direction-reversal symmetry, no station validation, generalised zone
cartography). The climatological basis is no longer provisional.

**Checkpoints.** Checkpoint 2's held item (30-yr pull) closed out — approved
by Jamie 2026-07-10, delivered this session.

**Next.** Candidates, Jamie's call: NZS 3604-style design-gust layer (annual
maxima now support a Gumbel fit); GitHub Pages deploy; Otago scale-up plan;
conda lockfile export.

## 2026-07-11 — Session 2: pull recovery, fetch restructure, interim 14-yr refresh

**Goal.** Recover the 30-yr pull after a power cut; work around a degraded
CDS queue; refresh the whole map from the years already downloaded.

**Decisions.**
- Power cut ~20:00 on 2026-07-10: all 81 downloaded months verified intact
  (zip integrity test — outage hit between requests); pull resumed, nothing
  refetched.
- CDS queue degraded from ~3 min/request (test day) to ~36 min/request.
  Probe verified a 1-variable x 1-year request passes the cost cap that
  rejects 3-variable years, so remaining years (2006-2020) fetch as 3
  per-variable yearly files each: ~47 queue waits instead of 182. Complete
  monthly years kept; 2004 finishes monthly (2 missing months).
- Interim refresh at Jamie's request from the 14 complete years on disk
  (1991-2003 + 2005; 2004 auto-excluded as partial). New safeguards so the
  interim run cannot poison tonight's final run: script 04 only ingests
  complete years; script 05 re-runs WindNinja when the cached run's input
  speed differs from the current climatology; webmap legend flags gappy
  year sets as "interim - download in progress".

**Provenance.** ERA5 as before; interim climatology = 981,696 samples,
14 years, p99 gust 22.0 m/s (2005-only was 20.3 — 2005 was a mild year).

**Residuals & caveats.**
- Mass-conserving solver is direction-reversal symmetric: opposite sectors
  (N/S, E/W, NE/SW, SE/NW) produce identical multiplier fields, so the 8
  sectors yield only 4 distinct terrain responses — no lee-side asymmetry.
  Inherent to the solver choice; would need NinjaFOAM to resolve.
- Interim gust surface 13.4-30.7 m/s (mean 22.6); worst-case max 35.2;
  still below the ~45 m/s design gust. Max/min ratio 2.29 (offshore minima).
- Zone breaks (smoothed field) shifted up ~1.5 m/s vs 2005-only:
  20.2/21.7/22.3/22.7/23.1/24.3 m/s. Zone geometry broadly similar; the
  Mt Cargill chain now forms a continuous Zone 5 ridge.
- 2004 rejoins the record automatically once its two missing months land.

**Checkpoints.** None new; all prior decisions carried.

**Next.** Runner (per-var-year mode) continues toward 2020; on completion
the automatic full refresh reruns 04-10 with all 30 years. Review, commit.

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
