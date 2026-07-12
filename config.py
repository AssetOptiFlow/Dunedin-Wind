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
LIGHTNING_DIR = DATA / "lightning"
LIGHTNING_SOURCE_TIF = LIGHTNING_DIR / "lightning_density_2000_14.tif"
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
