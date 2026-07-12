"""Single source of truth for the Dunedin-Wind pipeline.

All scripts import from here. Change values here, not in scripts.

Multi-domain: set WIND_DOMAIN=central to run the Central Otago/Queenstown
domain (data_central/, outputs_central/, webmap_central/); default is the
original Dunedin trial with its legacy flat layout.
"""
import os
from pathlib import Path

DOMAIN = os.environ.get("WIND_DOMAIN", "dunedin")
assert DOMAIN in ("dunedin", "central"), f"unknown WIND_DOMAIN {DOMAIN!r}"

# --- Paths ---------------------------------------------------------------
REPO = Path(__file__).parent
_suffix = "" if DOMAIN == "dunedin" else f"_{DOMAIN}"
DATA = REPO / f"data{_suffix}"
OUTPUTS = REPO / f"outputs{_suffix}"
DIAGNOSTICS = OUTPUTS / "diagnostics"
WEBMAP = REPO / f"webmap{_suffix}"

DEM_DIR = DATA / "dem"
ERA5_DIR = DATA / "era5"
WINDNINJA_DIR = DATA / "windninja"

# National / shared sources stay in the primary data dir for every domain.
SHARED_DATA = REPO / "data"

WINDNINJA_CLI = Path(r"C:\WindNinja\WindNinja-3.12.2\bin\WindNinja_cli.exe")

# --- Domain ----------------------------------------------------------------
# Bounding boxes, WGS84 (EPSG:4326).
# dunedin: the original trial. central: Aurora's Central Otago/Queenstown
# cluster — 20 zone-substation reach polygons + 10 km buffer (sized
# 2026-07-12 from the published Aurora KML).
if DOMAIN == "dunedin":
    BBOX = {"south": -46.1, "west": 170.0, "north": -45.7, "east": 170.8}
else:
    BBOX = {"south": -45.89, "west": 168.18, "north": -44.13, "east": 169.96}
# Buffer (m) added around bbox for DEM/WindNinja to avoid solver edge effects;
# trimmed off before any analysis output.
DEM_BUFFER_M = 5000

CRS_WGS84 = "EPSG:4326"
CRS_WORKING = "EPSG:32759"  # UTM 59S — projected metres, required by WindNinja

DEM_RES_M = 30    # native working resolution
GRID_RES_M = 500  # analysis/output grid

# --- ERA5 --------------------------------------------------------------------
ERA5_DATASET = "reanalysis-era5-single-levels"
ERA5_VARIABLES = [
    "10m_wind_gust_since_previous_post_processing",  # hourly-max gust (10fg)
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]
ERA5_YEARS = list(range(1991, 2021))  # 30-year climatology 1991-2020
ERA5_TEST_YEAR = 2005
GUST_PERCENTILE = 99

# --- Sectors ---------------------------------------------------------------
# 8 directional sectors, centres in degrees (wind FROM), meteorological.
SECTORS = [0, 45, 90, 135, 180, 225, 270, 315]
SECTOR_NAMES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# --- WindNinja ---------------------------------------------------------------
# domainAverageInitialization: verified correct for climatological,
# non-diurnal, domain-average runs (cli_domainAverage.cfg, WindNinja 3.12.2).
# NOTE: the 3.12.2 win64 build has no GeoTIFF output option -- we use ASCII
# AAIGRID output (_vel.asc / _ang.asc) and read it with rasterio.
# Solver mesh (separate from output resolution). 300 m on the 10x-larger
# central domain keeps runs tractable; logged as a screening trade-off.
WN_MESH_RES_M = 200 if DOMAIN == "dunedin" else 300
WN_VEGETATION = "grass"
WN_WIND_HEIGHT_M = 10.0      # input and output height (matches ERA5 10m)
WN_NUM_THREADS = 8
# Speed-up multipliers outside this range are clipped and logged.
MULT_CLIP = (0.2, 3.0)

# --- Confidence layer ---------------------------------------------------------
# Ordinal high/medium/low from min(distance score, terrain score).
# Distance thresholds (km) to nearest usable station -- Checkpoint 4 value.
STATION_DIST_HIGH_KM = 7.5
STATION_DIST_MED_KM = 15.0   # beyond this: low + no_station_within_threshold
# TRI terciles are computed from the actual distribution in script 07.

# Candidate stations (public metadata only; coordinates approximate to
# ~100 m, confidence distance anchors only — never calibration).
if DOMAIN == "dunedin":
    STATIONS = [
        {"name": "Dunedin Aerodrome AWS", "lat": -45.928, "lon": 170.198},
        {"name": "Dunedin, Musselburgh EWS", "lat": -45.901, "lon": 170.512},
        {"name": "Taiaroa Head", "lat": -45.774, "lon": 170.728},
    ]
else:
    STATIONS = [
        {"name": "Queenstown Aerodrome AWS", "lat": -45.021, "lon": 168.739},
        {"name": "Wanaka Airport AWS", "lat": -44.722, "lon": 169.246},
        {"name": "Alexandra EWS", "lat": -45.249, "lon": 169.393},
        {"name": "Cromwell EWS", "lat": -45.038, "lon": 169.203},
    ]

# --- Zones & arrows ------------------------------------------------------------
N_ZONES = 5                 # Zone 1 = lowest exposure ... Zone 5 = highest
# Checkpoint 6 fixed 2.5 km at the Dunedin extent; 7.5 km on the 10x-larger
# central domain preserves the same visual arrow density (~450 arrows).
ARROW_SPACING_M = 2500 if DOMAIN == "dunedin" else 7500
# Zone polygons are a cartographically generalised layer (Wellington-wind-
# zones look): Gaussian-smoothed field, contour-style nested thresholds,
# curved boundaries. The continuous gust raster stays quantitative.
ZONE_GAUSS_SIGMA_M = 1000    # smoothing of the field before classification
ZONE_UPSAMPLE = 5            # 500 m -> 100 m before contouring (curve quality)
ZONE_MIN_AREA_KM2 = 2.0      # drop zone islands / fill holes smaller than this
ZONE_BOUNDARY_SMOOTH_M = 250 # round-join buffer smoothing radius
LAND_MIN_ELEV_M = 1.0        # zones are clipped to land (council-map style)

# Internal rasters/science stay in m/s; user-facing display is km/h.
MS_TO_KMH = 3.6

# --- Lightning (historical strike density) -----------------------------------
# Source: MfE "Lightning strike density, 2000-14" (layer 52851), derived from
# the NZ Lightning Detection Network (NZLDN). 5 km cells, EPSG:2193, units =
# ground strikes per 25 km^2 cell per year. Licence CC BY 3.0 NZ.
# NZLDN point data is commercial (MetService) - density raster only.
LIGHTNING_DIR = SHARED_DATA / "lightning"  # national raster, shared by all domains
# Koordinates export keeps the original filename ("AnAve_div14" = annual
# average over the 14-year record; values are already strikes/25km^2/yr).
LIGHTNING_SOURCE_TIF = LIGHTNING_DIR / "LightningStrikeCount5km_02_AnAve_div14.tif"
LIGHTNING_SOURCE_URL = "https://data.mfe.govt.nz/layer/52851-lightning-strike-density-200014/"
LIGHTNING_NATIVE_RES_M = 5000     # honest resolution; never resampled to 500 m
LIGHTNING_DISPLAY_SIGMA_M = 2500  # Gaussian display smoothing only
LIGHTNING_PERIOD = "2000-14"
LIGHTNING_ATTRIBUTION = "NZLDN via MfE, CC BY 3.0 NZ"
LIGHTNING_UNCERTAINTY = (
    "Underlying data 5 km native (display smoothed). Coastal Otago strike "
    "counts are low: roughly 10-30 strikes per 5 km cell over 2000-14, so "
    "finer resolution is not statistically supportable."
)

UNCERTAINTY_STATEMENT = (
    "Modelled screening estimate (ERA5 + WindNinja terrain adjustment). "
    "Not a validated measurement; do not use for engineering design."
)
