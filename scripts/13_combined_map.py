"""Single combined webmap covering both domains with ALIGNED zones.

One Jenks break set is computed on the POOLED smoothed gust fields of both
domains and applied to each, so "Zone 4" means the same speed band
everywhere. Consequence (by construction): Dunedin, mid-range next to the
alpine extremes, occupies mostly the middle zones on the combined map — its
own map keeps the finer domain-local contrast.

Reads both domains' existing outputs (file-driven; run after both domains
are built). Writes outputs_combined/ + webmap_combined/index.html.
Raster colour scales (gust, lightning) are shared across domains.
"""
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import Resampling
import geopandas as gpd
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
import _zones_core as core
from _util import reproject_to_wgs84

REPO = C.REPO
OUT = REPO / "outputs_combined"
WEB = REPO / "webmap_combined"
DOMAINS = [
    {"key": "dunedin", "title": "Dunedin", "out": REPO / "outputs",
     "data": REPO / "data", "web": REPO / "webmap"},
    {"key": "central", "title": "Central Otago/Queenstown",
     "out": REPO / "outputs_central", "data": REPO / "data_central",
     "web": REPO / "webmap_central"},
]
GUST_CMAP, LIGHTNING_CMAP = "YlOrRd", "Blues"
ZONE_COLORS = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]
CONF_COLORS = {3: (26, 152, 80, 140), 2: (254, 196, 79, 150), 1: (215, 48, 39, 150)}
ARROW_TARGET_SPACING_M = 7500
# Everything displayed is clipped to the Aurora service area + this buffer.
CLIP_BUFFER_M = 10_000


def service_clip():
    """Union of all substation reach polygons + generous buffer.
    Returns (clip in CRS_WORKING, clip in WGS84)."""
    g = gpd.read_file(C.SHARED_DATA / "substations" /
                      "aurora_zone_substations.geojson")
    g = g[g.geometry.geom_type == "Polygon"].to_crs(C.CRS_WORKING)
    clip_utm = g.union_all().buffer(CLIP_BUFFER_M)
    clip_wgs = gpd.GeoSeries([clip_utm], crs=C.CRS_WORKING) \
        .to_crs(C.CRS_WGS84).iloc[0]
    return clip_utm, clip_wgs


def pooled_breaks():
    import jenkspy
    vals = []
    for d in DOMAINS:
        smooth, finite, _ = core.smoothed_field(d["out"] / "gust" / "gust99_500m.tif")
        vals.append(smooth[finite].ravel())
    pooled = np.sort(np.concatenate(vals))
    sample = pooled[np.linspace(0, pooled.size - 1, 40_000).astype(int)]
    bs = jenkspy.jenks_breaks(sample, n_classes=C.N_ZONES)
    bs[0], bs[-1] = float(pooled[0]), float(pooled[-1])
    return [float(b) for b in bs]


def aligned_zones(bs, clip_utm):
    frames = []
    for d in DOMAINS:
        gdf, zones_r, transform = core.generalise(
            d["out"] / "gust" / "gust99_500m.tif",
            d["data"] / "dem" / "land_500m.tif", bs)
        gdf["domain"] = d["title"]
        gdf["geometry"] = gdf.geometry.intersection(clip_utm)
        gdf = gdf[~gdf.geometry.is_empty]
        frames.append(gdf)
        with rasterio.open(d["out"] / "gust" / "gust99_500m.tif") as src:
            prof = src.profile.copy()
        prof.update(dtype="uint8", nodata=0)
        zr = OUT / f"zones_aligned_{d['key']}.tif"
        with rasterio.open(zr, "w", **prof) as dst:
            dst.write(zones_r, 1)
        reproject_to_wgs84(zr, OUT / f"zones_aligned_{d['key']}_wgs84.tif",
                           resampling=Resampling.nearest)
    gdf = gpd.GeoDataFrame(
        __import__("pandas").concat(frames, ignore_index=True), crs=C.CRS_WORKING)
    gdf["label"] = gdf["zone"].map(lambda z: f"Zone {z}")
    gdf["gust_range_ms"] = gdf["zone"].map(lambda z: f"{bs[z-1]:.1f}-{bs[z]:.1f}")
    gdf["gust_range_kmh"] = gdf["zone"].map(
        lambda z: f"{bs[z-1]*C.MS_TO_KMH:.0f}-{bs[z]*C.MS_TO_KMH:.0f}")
    gdf["scheme"] = "jenks (pooled across domains)"
    gdf["note"] = (C.UNCERTAINTY_STATEMENT + " Zones aligned across domains "
                   "via pooled breaks; boundaries generalised (1 km smoothing).")
    for _, r in gdf.iterrows():
        print(f"  {r['domain']:>26} Zone {r['zone']}: {r['gust_range_kmh']} km/h "
              f"{r.geometry.area/1e6:.0f} km^2")
    gdf = gdf.to_crs(C.CRS_WGS84)
    gdf.to_file(OUT / "zones_aligned.geojson", driver="GeoJSON")
    return gdf


def merged_arrows(clip_utm):
    from shapely.geometry import Point
    from shapely.prepared import prep
    clip = prep(clip_utm)
    feats = []
    for d in DOMAINS:
        gj = json.loads((d["out"] / "arrows.geojson").read_text())
        fs = gj["features"]
        # Thin to a uniform ~7.5 km so densities match across domains.
        to_utm = Transformer.from_crs(C.CRS_WGS84, C.CRS_WORKING, always_xy=True)
        seen = set()
        for f in fs:
            lon, lat = f["geometry"]["coordinates"]
            x, y = to_utm.transform(lon, lat)
            if not clip.contains(Point(x, y)):
                continue
            key = (round(x / ARROW_TARGET_SPACING_M), round(y / ARROW_TARGET_SPACING_M))
            if key in seen:
                continue
            seen.add(key)
            feats.append(f)
    print(f"  arrows: {len(feats)} at ~{ARROW_TARGET_SPACING_M} m")
    return {"type": "FeatureCollection", "features": feats}


def merged_points(name):
    feats = []
    for d in DOMAINS:
        p = d["web"] / name
        if p.exists():
            feats.extend(json.loads(p.read_text())["features"])
    return {"type": "FeatureCollection", "features": feats}


def merged_substations():
    frames = []
    for d in DOMAINS:
        g = gpd.read_file(d["out"] / "substations_exposure.geojson")
        with rasterio.open(OUT / f"zones_aligned_{d['key']}_wgs84.tif") as src:
            zones = src.read(1)
            transform, shp = src.transform, src.shape
        dz, p45 = [], []
        for _, r in g.iterrows():
            inside = ~geometry_mask([r.geometry], out_shape=shp,
                                    transform=transform, invert=False,
                                    all_touched=True)
            z = zones[inside & (zones > 0)]
            dz.append(int(np.bincount(z).argmax()) if z.size else None)
            p45.append(round(100 * float((z >= 4).mean())) if z.size else None)
        g["dominant_zone"] = dz
        g["pct_zone_4_5"] = p45
        g["domain"] = d["title"]
        frames.append(g)
    out = gpd.GeoDataFrame(
        __import__("pandas").concat(frames, ignore_index=True), crs=C.CRS_WGS84)
    out.to_file(OUT / "substations_exposure_aligned.geojson", driver="GeoJSON")
    return out


def overlay(path, cmap, vmin, vmax, categorical=None, clip_wgs=None):
    with rasterio.open(path) as src:
        a = src.read(1)
        b = src.bounds
        nodata = src.nodata
        transform, shp = src.transform, src.shape
    if nodata is not None:
        a = np.where(a == nodata, np.nan, a)
    if categorical:
        rgba = np.zeros(a.shape + (4,), dtype="uint8")
        for v, col in categorical.items():
            rgba[a == v] = col
    else:
        mask = ~np.isfinite(a)
        norm = np.clip((a - vmin) / (vmax - vmin), 0, 1)
        rgba = (colormaps[cmap](norm) * 255).astype("uint8")
        rgba[..., 3] = np.where(mask, 0, 200)
    if clip_wgs is not None:
        inside = ~geometry_mask([clip_wgs], out_shape=shp, transform=transform,
                                invert=False, all_touched=True)
        rgba[..., 3] = np.where(inside, rgba[..., 3], 0)
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return uri, [[b.bottom, b.left], [b.top, b.right]]


def shared_range(paths, lo=1, hi=99.5):
    vals = []
    for p in paths:
        with rasterio.open(p) as src:
            a = src.read(1)
            if src.nodata is not None:
                a = np.where(a == src.nodata, np.nan, a)
            vals.append(a[np.isfinite(a)])
    v = np.concatenate(vals)
    return float(np.percentile(v, lo)), float(np.percentile(v, hi))


def ramp_uri(cmap):
    grad = np.tile(np.linspace(0, 1, 256), (18, 1))
    rgba = (colormaps[cmap](grad) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "diagnostics").mkdir(exist_ok=True)
    WEB.mkdir(exist_ok=True)

    bs = pooled_breaks()
    print(f"pooled breaks: {[f'{b:.1f}' for b in bs]} m/s "
          f"({[f'{b*C.MS_TO_KMH:.0f}' for b in bs]} km/h)")
    (OUT / "pooled_breaks.json").write_text(json.dumps(bs))

    clip_utm, clip_wgs = service_clip()
    print(f"clip: service area + {CLIP_BUFFER_M/1000:.0f} km buffer "
          f"({clip_utm.area/1e6:.0f} km^2)")

    zones = aligned_zones(bs, clip_utm)
    arrows = merged_arrows(clip_utm)
    stations = merged_points("stations.geojson")
    subs = merged_substations()

    gust_paths = [d["out"] / "gust" / "gust99_500m_wgs84.tif" for d in DOMAINS]
    gvmin, gvmax = shared_range(gust_paths)
    gust_ovls = [overlay(p, GUST_CMAP, gvmin, gvmax, clip_wgs=clip_wgs)
                 for p in gust_paths]
    conf_ovls = [overlay(d["out"] / "confidence" / "confidence_500m_wgs84.tif",
                         None, 0, 0, categorical=CONF_COLORS,
                         clip_wgs=clip_wgs) for d in DOMAINS]
    lt_paths = [d["out"] / "lightning" / "lightning_density_display_wgs84.tif"
                for d in DOMAINS]
    lt_paths = [p for p in lt_paths if p.exists()]
    lt_ovls, lt_range = [], (0, 0)
    if lt_paths:
        lt_range = shared_range(lt_paths)
        lt_ovls = [overlay(p, LIGHTNING_CMAP, *lt_range, clip_wgs=clip_wgs)
                   for p in lt_paths]

    def group_js(ovls, opacity):
        items = ", ".join(f"L.imageOverlay('{u}', {json.dumps(b)}, "
                          f"{{opacity: {opacity}}})" for u, b in ovls)
        return f"L.layerGroup([{items}])"

    zone_rows = "".join(
        f'<div class="row"><span class="swatch" style="background:{ZONE_COLORS[z-1]}">'
        f'</span>Zone {z} &nbsp;{bs[z-1]*C.MS_TO_KMH:.0f}-{bs[z]*C.MS_TO_KMH:.0f} km/h</div>'
        for z in range(1, C.N_ZONES + 1))
    lightning_legend = ""
    if lt_ovls:
        lightning_legend = f"""
    <h4>Lightning strike density (2000-14)</h4>
    <img src="{ramp_uri(LIGHTNING_CMAP)}" style="width:100%;height:12px"><div class="row"
      style="justify-content:space-between"><span>{lt_range[0]:.02f}</span>
      <span style="color:#666">strikes/km&sup2;/yr &middot; 5 km native</span><span>{lt_range[1]:.02f}</span></div>
    <div class="row" style="color:#444">{C.LIGHTNING_ATTRIBUTION}</div>"""

    vendor = REPO / "webmap" / "vendor"
    html = TEMPLATE
    for k, v in {
        "@LEAFLET_CSS@": (vendor / "leaflet.css").read_text(encoding="utf-8"),
        "@LEAFLET_JS@": (vendor / "leaflet.js").read_text(encoding="utf-8"),
        "@GUST_GROUP@": group_js(gust_ovls, .75),
        "@CONF_GROUP@": group_js(conf_ovls, .8),
        "@LT_GROUP@": group_js(lt_ovls, .75) if lt_ovls else "L.layerGroup([])",
        "@ZONES@": (OUT / "zones_aligned.geojson").read_text(),
        "@ARROWS@": json.dumps(arrows),
        "@STATIONS@": json.dumps(stations),
        "@SUBS@": subs.to_json(),
        "@ZONE_COLORS@": json.dumps(ZONE_COLORS),
        "@ZONE_RANGES@": json.dumps(
            [f"{bs[z-1]*C.MS_TO_KMH:.0f}-{bs[z]*C.MS_TO_KMH:.0f}"
             for z in range(1, C.N_ZONES + 1)]),
        "@ZONE_ROWS@": zone_rows,
        "@LIGHTNING_LEGEND@": lightning_legend,
        "@RAMP_URI@": ramp_uri(GUST_CMAP),
        "@GVMIN@": f"{gvmin * C.MS_TO_KMH:.0f}",
        "@GVMAX@": f"{gvmax * C.MS_TO_KMH:.0f}",
        "@UNCERTAINTY@": C.UNCERTAINTY_STATEMENT,
    }.items():
        html = html.replace(k, v)
    out = WEB / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aurora network wind gust exposure — combined screening map</title>
<style>@LEAFLET_CSS@</style>
<style>
  html, body, #map { height: 100%; margin: 0; }
  .legend { background: rgba(255,255,255,.94); padding: 10px 12px;
    border-radius: 6px; box-shadow: 0 1px 5px rgba(0,0,0,.4);
    font: 12px/1.45 system-ui, sans-serif; max-width: 260px; }
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
const map = L.map('map');
map.fitBounds([[-46.1, 168.18], [-44.13, 170.8]]);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 17, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const gust = @GUST_GROUP@;
const confidence = @CONF_GROUP@;
const lightning = @LT_GROUP@;

const zoneColors = @ZONE_COLORS@;
const zonesData = @ZONES@;
let zoneOpacity = 0.55;
const zoneLayers = {};
for (let z = 1; z <= 5; z++) {
  zoneLayers[z] = L.geoJSON(zonesData, {
    filter: f => f.properties.zone === z,
    style: f => ({stroke: false,
                  fillColor: zoneColors[f.properties.zone - 1],
                  fillOpacity: zoneOpacity}),
    onEachFeature: (f, l) => l.bindPopup(
      `<b>${f.properties.label}</b> (${f.properties.domain})` +
      `<br>p99 gust ${f.properties.gust_range_kmh} km/h` +
      ` (${f.properties.gust_range_ms} m/s)<br><i>${f.properties.note}</i>`)
  });
}
function setZoneOpacity(v) {
  zoneOpacity = v;
  for (let z = 1; z <= 5; z++) zoneLayers[z].setStyle({fillOpacity: v});
}

function arrowIcon(bearing, speed, vmin, vmax) {
  const t = Math.min(1, Math.max(0, (speed - vmin) / (vmax - vmin)));
  const size = 16 + 14 * t;
  const hue = 210 - 210 * t;
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
               `<br>p99 gust ~${f.properties.speed_kmh} km/h`)
});

const subs = L.geoJSON(@SUBS@, {
  style: {color: '#222', weight: 2, dashArray: '5 3', fillOpacity: 0},
  onEachFeature: (f, l) => {
    const p = f.properties;
    l.bindPopup(`<b>${p.name}</b> — ${p.gxp} (${p.domain})<br>` +
      `p99 gust mean ${p.gust99_mean_kmh} / max ${p.gust99_max_kmh} km/h<br>` +
      `absolute max (worst sector) ${p.absolute_max_kmh} km/h<br>` +
      `dominant aligned Zone ${p.dominant_zone}, ${p.pct_zone_4_5}% in Zones 4–5<br>` +
      `${p.pct_conf_low}% of area low-confidence<br><i>${p.note}</i>`);
  }
});

const stations = L.geoJSON(@STATIONS@, {
  pointToLayer: (f, ll) => L.marker(ll, {icon: L.divIcon({className: 'stn',
    html: '<div></div>', iconSize: [10, 10]})})
    .bindPopup(`<b>${f.properties.name}</b><br>${f.properties.role}`)
});

for (let z = 1; z <= 5; z++) zoneLayers[z].addTo(map);
arrows.addTo(map); subs.addTo(map); stations.addTo(map);
const zoneRanges = @ZONE_RANGES@;
const overlays = {
  'Gust speed (continuous, shared scale)': gust,
};
for (let z = 1; z <= 5; z++) {
  overlays[`Zone ${z} (${zoneRanges[z-1]} km/h)`] = zoneLayers[z];
}
Object.assign(overlays, {
  'Direction arrows': arrows,
  'Confidence band': confidence,
  'Lightning strike density': lightning,
  'Zone substation areas (Aurora)': subs,
  'Stations (context)': stations,
});
L.control.layers(null, overlays, {collapsed: false}).addTo(map);

// Zone transparency slider (applies to all five zone layers).
const opacityCtl = L.control({position: 'topright'});
opacityCtl.onAdd = () => {
  const d = L.DomUtil.create('div', 'legend');
  d.innerHTML = `Zone transparency<br>
    <input id="zop" type="range" min="0" max="100" value="${zoneOpacity*100}"
      style="width:140px">`;
  L.DomEvent.disableClickPropagation(d);
  d.querySelector('#zop').addEventListener('input',
    e => setZoneOpacity(e.target.value / 100));
  return d;
};
opacityCtl.addTo(map);

const legend = L.control({position: 'bottomright'});
legend.onAdd = () => {
  const d = L.DomUtil.create('div', 'legend');
  d.innerHTML = `
    <h4>p99 gust estimate (km/h), ERA5 1991-2020</h4>
    <img src="@RAMP_URI@" style="width:100%;height:12px"><div class="row"
      style="justify-content:space-between"><span>@GVMIN@</span>
      <span style="color:#666">shared scale, both domains</span><span>@GVMAX@</span></div>
    <h4>Aligned exposure zones (pooled Jenks)</h4>@ZONE_ROWS@
    <div class="row" style="color:#444">one break set for both domains —
      Dunedin sits mid-range next to alpine extremes by construction</div>
    <div class="row" style="color:#444">map clipped to the Aurora service
      area + 10 km buffer</div>
    <h4>Direction arrows</h4>
    <div class="row">point downwind; size/colour = local p99 gust</div>
    <h4>Confidence</h4>
    <div class="row"><span class="swatch" style="background:rgb(26,152,80)"></span>high</div>
    <div class="row"><span class="swatch" style="background:rgb(254,196,79)"></span>medium</div>
    <div class="row"><span class="swatch" style="background:rgb(215,48,39)"></span>low — sparse stations and/or complex terrain</div>
    @LIGHTNING_LEGEND@
    <h4>Zone substation areas</h4>
    <div class="row">dashed outlines; click for per-substation stats</div>
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
