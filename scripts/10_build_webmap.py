"""Assemble the self-contained Leaflet webmap (webmap/index.html).

Everything except the OSM basemap tiles is embedded in the single HTML file:
  - Leaflet JS/CSS inlined (downloaded once to webmap/vendor/, cached)
  - gust + confidence rasters as base64 PNG imageOverlays
  - zones / arrows / stations as inline GeoJSON
  - combined legend for all four layers + fixed uncertainty statement
"""
import base64
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

VENDOR = C.WEBMAP / "vendor"
LEAFLET = {
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
}
GUST_CMAP = "YlOrRd"
CONF_COLORS = {3: (26, 152, 80, 140), 2: (254, 196, 79, 150), 1: (215, 48, 39, 150)}
ZONE_COLORS = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]


def vendor(name):
    VENDOR.mkdir(parents=True, exist_ok=True)
    p = VENDOR / name
    if not p.exists():
        urllib.request.urlretrieve(LEAFLET[name], p)
    return p.read_text(encoding="utf-8")


def raster_overlay(path, kind):
    """Colour a WGS84 raster to PNG; return (data_uri, [[S,W],[N,E]], vmin, vmax)."""
    with rasterio.open(path) as src:
        a = src.read(1)
        b = src.bounds
        nodata = src.nodata
    if kind == "gust":
        mask = ~np.isfinite(a)
        vmin, vmax = np.nanpercentile(a[~mask], [1, 99.5])
        norm = np.clip((a - vmin) / (vmax - vmin), 0, 1)
        rgba = (colormaps[GUST_CMAP](norm) * 255).astype("uint8")
        rgba[..., 3] = np.where(mask, 0, 200)
    else:  # confidence, categorical uint8 1..3 (0 = nodata)
        mask = (a == (nodata or 0))
        rgba = np.zeros(a.shape + (4,), dtype="uint8")
        for v, col in CONF_COLORS.items():
            rgba[a == v] = col
        rgba[mask] = 0
        vmin = vmax = None
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return uri, [[b.bottom, b.left], [b.top, b.right]], vmin, vmax


def ramp_uri(vmin, vmax):
    grad = np.tile(np.linspace(0, 1, 256), (18, 1))
    rgba = (colormaps[GUST_CMAP](grad) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    gust_uri, gust_bounds, vmin, vmax = raster_overlay(
        C.OUTPUTS / "gust" / "gust99_500m_wgs84.tif", "gust")
    conf_uri, conf_bounds, _, _ = raster_overlay(
        C.OUTPUTS / "confidence" / "confidence_500m_wgs84.tif", "conf")
    zones = (C.OUTPUTS / "zones.geojson").read_text()
    arrows = (C.OUTPUTS / "arrows.geojson").read_text()
    stations = (C.WEBMAP / "stations.geojson").read_text()
    zone_meta = json.loads(zones)
    zone_ranges = {f["properties"]["zone"]: f["properties"]["gust_range_ms"]
                   for f in zone_meta["features"]}
    scheme = zone_meta["features"][0]["properties"]["scheme"]
    clim = json.loads((C.OUTPUTS / "era5_climatology.json").read_text())

    zone_rows = "".join(
        f'<div class="row"><span class="swatch" style="background:{ZONE_COLORS[z-1]}">'
        f'</span>Zone {z} &nbsp;{zone_ranges[z]} m/s</div>'
        for z in sorted(zone_ranges))

    html = HTML_TEMPLATE
    for k, v in {
        "@LEAFLET_CSS@": vendor("leaflet.css"),
        "@LEAFLET_JS@": vendor("leaflet.js"),
        "@GUST_URI@": gust_uri,
        "@GUST_BOUNDS@": json.dumps(gust_bounds),
        "@CONF_URI@": conf_uri,
        "@CONF_BOUNDS@": json.dumps(conf_bounds),
        "@ZONES@": zones,
        "@ARROWS@": arrows,
        "@STATIONS@": stations,
        "@RAMP_URI@": ramp_uri(vmin, vmax),
        "@VMIN@": f"{vmin:.0f}",
        "@VMAX@": f"{vmax:.0f}",
        "@ZONE_ROWS@": zone_rows,
        "@SCHEME@": scheme,
        "@ZONE_COLORS@": json.dumps(ZONE_COLORS),
        "@UNCERTAINTY@": C.UNCERTAINTY_STATEMENT,
        "@YEARS@": (f"{min(clim['years'])}-{max(clim['years'])}"
                    if len(clim["years"]) > 1
                    else f"{clim['years'][0]} (single year, provisional)"),
        "@CENTER@": json.dumps([(C.BBOX["south"] + C.BBOX["north"]) / 2,
                                (C.BBOX["west"] + C.BBOX["east"]) / 2]),
    }.items():
        html = html.replace(k, v)
    out = C.WEBMAP / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dunedin wind gust exposure — screening estimate</title>
<style>@LEAFLET_CSS@</style>
<style>
  html, body, #map { height: 100%; margin: 0; }
  .legend {
    background: rgba(255,255,255,.94); padding: 10px 12px; border-radius: 6px;
    box-shadow: 0 1px 5px rgba(0,0,0,.4); font: 12px/1.45 system-ui, sans-serif;
    max-width: 250px;
  }
  .legend h4 { margin: 6px 0 3px; font-size: 12px; }
  .legend .row { display: flex; align-items: center; gap: 6px; margin: 1px 0; }
  .swatch { display: inline-block; width: 14px; height: 14px; border: 1px solid #777; }
  .uncert { margin-top: 8px; padding-top: 6px; border-top: 1px solid #ccc;
            font-style: italic; color: #444; }
  .arrow-icon svg { display: block; }
  .stn div { width: 10px; height: 10px; border-radius: 50%;
             background: #333; border: 2px solid #fff; }
</style>
</head>
<body>
<div id="map"></div>
<script>@LEAFLET_JS@</script>
<script>
const map = L.map('map').setView(@CENTER@, 11);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 17, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const gust = L.imageOverlay('@GUST_URI@', @GUST_BOUNDS@, {opacity: .75});
const confidence = L.imageOverlay('@CONF_URI@', @CONF_BOUNDS@, {opacity: .8});

const zoneColors = @ZONE_COLORS@;
const zones = L.geoJSON(@ZONES@, {
  style: f => ({color: '#333', weight: 1.2,
                fillColor: zoneColors[f.properties.zone - 1], fillOpacity: .45}),
  onEachFeature: (f, l) => l.bindPopup(
    `<b>${f.properties.label}</b><br>p99 gust ${f.properties.gust_range_ms} m/s` +
    `<br><i>${f.properties.note}</i>`)
});

function arrowIcon(bearing, speed, vmin, vmax) {
  const t = Math.min(1, Math.max(0, (speed - vmin) / (vmax - vmin)));
  const size = 16 + 14 * t;
  const hue = 210 - 210 * t;   // blue (slow) -> red (fast)
  // glyph points up (N); rotate so it points DOWNWIND (bearing = wind FROM)
  const rot = (bearing + 180) % 360;
  return L.divIcon({className: 'arrow-icon', iconSize: [size, size],
    html: `<svg width="${size}" height="${size}" viewBox="0 0 20 20"
      style="transform: rotate(${rot}deg)">
      <path d="M10 1 L15 13 L10 10 L5 13 Z"
        fill="hsl(${hue},85%,45%)" stroke="#222" stroke-width=".7"/></svg>`});
}
const arrowData = @ARROWS@;
const speeds = arrowData.features.map(f => f.properties.speed_ms);
const sMin = Math.min(...speeds), sMax = Math.max(...speeds);
const arrows = L.geoJSON(arrowData, {
  pointToLayer: (f, ll) => L.marker(ll,
    {icon: arrowIcon(f.properties.bearing_deg, f.properties.speed_ms, sMin, sMax)})
    .bindPopup(`wind from <b>${f.properties.sector}</b>` +
               `<br>p99 gust ~${f.properties.speed_ms} m/s`)
});

const stations = L.geoJSON(@STATIONS@, {
  pointToLayer: (f, ll) => L.marker(ll, {icon: L.divIcon({className: 'stn',
    html: '<div></div>', iconSize: [10, 10]})})
    .bindPopup(`<b>${f.properties.name}</b><br>${f.properties.role}`)
});

gust.addTo(map); arrows.addTo(map); stations.addTo(map);
L.control.layers(null, {
  'Gust speed (continuous)': gust,
  'Exposure zones (1–5)': zones,
  'Direction arrows': arrows,
  'Confidence band': confidence,
  'Stations (context)': stations,
}, {collapsed: false}).addTo(map);

const legend = L.control({position: 'bottomright'});
legend.onAdd = () => {
  const d = L.DomUtil.create('div', 'legend');
  d.innerHTML = `
    <h4>p99 gust estimate (m/s), ERA5 @YEARS@</h4>
    <img src="@RAMP_URI@" style="width:100%;height:12px"><div class="row"
      style="justify-content:space-between"><span>@VMIN@</span>
      <span style="color:#666">1&ndash;99.5 pctile stretch</span><span>@VMAX@</span></div>
    <h4>Exposure zones (@SCHEME@ breaks)</h4>@ZONE_ROWS@
    <h4>Direction arrows</h4>
    <div class="row">point downwind; size/colour = local p99 gust</div>
    <h4>Confidence</h4>
    <div class="row"><span class="swatch" style="background:rgb(26,152,80)"></span>high</div>
    <div class="row"><span class="swatch" style="background:rgb(254,196,79)"></span>medium</div>
    <div class="row"><span class="swatch" style="background:rgb(215,48,39)"></span>low — sparse stations and/or complex terrain</div>
    <div class="uncert">@UNCERTAINTY@</div>`;
  return d;
};
legend.addTo(map);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
