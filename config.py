"""Single source of truth for the Dunedin-Wind pipeline.

All scripts import from here. Change values here, not in scripts.
"""
from pathlib import Path

# --- Paths ---------------------------------------------------------------
REPO = Path(__file__).parent
DATA = REPO / "data"
OUTPUTS = REPO / "outputs"
DIAGNOSTICS = OUTPUTS / "diagnostics"
WEBMAP = REPO / "webmap"

DEM_DIR = DATA / "dem"
ERA5_DIR = DATA / "era5"
WINDNINJA_DIR = DATA / "windninja"

WINDNINJA_CLI = Path(r"C:\WindNinja\WindNinja-3.12.2\bin\WindNinja_cli.exe")

# --- Domain ----------------------------------------------------------------
# Bounding box, WGS84 (EPSG:4326). Dunedin region trial before full Otago.
BBOX = {"south": -46.1, "west": 170.0, "north": -45.7, "east": 170.8}
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
WN_MESH_RES_M = 200          # solver mesh (separate from output resolution)
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

# Candidate stations (public metadata only; coordinates confirmed in script 07
# with source URLs recorded in webmap/stations.geojson).
STATIONS = [
    {"name": "Dunedin Aerodrome AWS", "lat": -45.928, "lon": 170.198},
    {"name": "Dunedin, Musselburgh EWS", "lat": -45.901, "lon": 170.512},
    {"name": "Taiaroa Head", "lat": -45.774, "lon": 170.728},
]

# --- Zones & arrows ------------------------------------------------------------
N_ZONES = 5                 # Zone 1 = lowest exposure ... Zone 5 = highest
ARROW_SPACING_M = 2500      # Checkpoint 6 value (~5x5 analysis cells)
# Zone cluster cleanup: majority-smooth passes, then sieve patches smaller
# than this many 500 m cells (8 cells = 2 km^2) into the surrounding zone.
ZONE_SMOOTH_PASSES = 1
ZONE_MIN_PATCH_CELLS = 8

# Internal rasters/science stay in m/s; user-facing display is km/h.
MS_TO_KMH = 3.6

UNCERTAINTY_STATEMENT = (
    "Modelled screening estimate (ERA5 + WindNinja terrain adjustment). "
    "Not a validated measurement; do not use for engineering design."
)
