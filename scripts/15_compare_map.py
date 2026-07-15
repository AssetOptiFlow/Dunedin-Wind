"""Build the year-comparison webmap (webmap_compare/index.html).

Shows ONE overlay: the per-cell RELATIVE DIFFERENCE in p99 gust between two
user-chosen periods, (B - A) / A, on a diverging blue-0-red scale (red =
windier in B). Each period is the mean of its years' annual surfaces from
14_yearly_gust.py. Spatial structure in the difference reflects how each
period's directional mix loads the (climatological) WindNinja terrain
response — interannual signal is ERA5's.

Years are embedded as grayscale "data PNGs" (byte = gust on one fixed
absolute scale, alpha = strictly 0/255 validity); the browser averages the
selected spans and computes the difference client-side, so any period works
offline from one self-contained file. The diverging display range is FIXED
(worst single-year-pair 99.5th-percentile |relative difference|, rounded up
to 5%) so colours mean the same thing across selections.

Everything is clipped to the Aurora service area + 10 km, like the combined
map. Standalone read-only build: never touches the other webmaps. Rerun
after 14 whenever new years land.
"""
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

REPO = C.REPO
IN = REPO / "outputs_compare"
WEB = REPO / "webmap_compare"
DOMAIN_KEYS = ["dunedin", "central"]
DIV_CMAP = "RdBu_r"   # red = windier in B, blue = calmer, white ~ no change
CLIP_BUFFER_M = 10_000


def service_clip_wgs():
    import geopandas as gpd
    g = gpd.read_file(C.SHARED_DATA / "substations" /
                      "aurora_zone_substations.geojson")
    g = g[g.geometry.geom_type == "Polygon"].to_crs(C.CRS_WORKING)
    clip = g.union_all().buffer(CLIP_BUFFER_M)
    return gpd.GeoSeries([clip], crs=C.CRS_WORKING).to_crs(C.CRS_WGS84).iloc[0]


def read_surface(path):
    with rasterio.open(path) as src:
        a = src.read(1).astype("float64")
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
        return a, src.bounds, src.transform


def data_png(a, valid, vmin, vmax):
    """Grayscale+alpha PNG: byte = scaled value, alpha strictly 0/255 (canvas
    premultiplies alpha, so partial alpha would corrupt the data channel)."""
    byte = np.clip(np.nan_to_num((a - vmin) / (vmax - vmin)), 0, 1)
    byte = np.round(byte * 255).astype("uint8")
    la = np.dstack([byte, np.where(valid, 255, 0).astype("uint8")])
    buf = io.BytesIO()
    Image.fromarray(la, mode="LA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def ramp_uri(cmap):
    grad = np.tile(np.linspace(0, 1, 256), (18, 1))
    rgba = (colormaps[cmap](grad) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def diff_display_range(per_dom_arrays):
    """Fixed diverging range: max over all single-year pairs of the 99.5th
    percentile |(y_j - y_i) / y_i|, cell-subsampled, rounded UP to 5%."""
    worst = 0.0
    for arrs in per_dom_arrays.values():
        sub = [a[::7] for a in arrs]  # every 7th valid cell is plenty
        for i in range(len(sub)):
            for j in range(len(sub)):
                if i == j:
                    continue
                d = np.percentile(np.abs((sub[j] - sub[i]) / sub[i]), 99.5)
                worst = max(worst, float(d))
    return np.ceil(worst * 20) / 20


def main():
    stats = json.loads((IN / "yearly_stats.json").read_text())
    clip_wgs = service_clip_wgs()

    # Pass 1: load every year x domain; pooled fixed ABSOLUTE byte scale.
    surfaces, valids, pool = {}, {}, []
    for dom in DOMAIN_KEYS:
        years = sorted(stats["domains"][dom]["years"])
        for i, y in enumerate(years):
            a, bounds, transform = read_surface(
                IN / dom / f"gust99_{y}_500m_wgs84.tif")
            if i == 0:
                inside = ~geometry_mask([clip_wgs], out_shape=a.shape,
                                        transform=transform, invert=False,
                                        all_touched=True)
            valid = np.isfinite(a) & inside
            surfaces[dom, y] = (a, bounds)
            valids[dom] = valid
            pool.append(a[valid])
    pool = np.concatenate(pool)
    vmin = float(np.percentile(pool, 1))
    vmax = float(np.percentile(pool, 99.5))

    per_dom = {dom: [surfaces[dom, y][0][valids[dom]]
                     for y in sorted(stats["domains"][dom]["years"])]
               for dom in DOMAIN_KEYS}
    drange = diff_display_range(per_dom)
    print(f"absolute byte scale {vmin:.1f}-{vmax:.1f} m/s, "
          f"{len(surfaces)} year-surfaces; diff display range ±{drange*100:.0f}%")

    imgs, bounds_js, years_js = {}, {}, {}
    for dom in DOMAIN_KEYS:
        years = sorted(stats["domains"][dom]["years"])
        years_js[dom] = [int(y) for y in years]
        imgs[dom] = {}
        for y in years:
            a, b = surfaces[dom, y]
            imgs[dom][y] = data_png(a, valids[dom], vmin, vmax)
        bounds_js[dom] = [[b.bottom, b.left], [b.top, b.right]]

    div_lut = (colormaps[DIV_CMAP](np.linspace(0, 1, 256))[:, :3] * 255) \
        .astype(int).tolist()

    side_stats = {dom: {str(y): {"mean_ms": v["clip_mean_ms"],
                                 "cells": v["clip_cells"]}
                        for y, v in stats["domains"][dom]["years"].items()}
                  for dom in DOMAIN_KEYS}

    vendor = REPO / "webmap" / "vendor"
    html = TEMPLATE
    for k, v in {
        "@LEAFLET_CSS@": (vendor / "leaflet.css").read_text(encoding="utf-8"),
        "@LEAFLET_JS@": (vendor / "leaflet.js").read_text(encoding="utf-8"),
        "@IMGS@": json.dumps(imgs),
        "@BOUNDS@": json.dumps(bounds_js),
        "@YEARS@": json.dumps(years_js),
        "@STATS@": json.dumps(side_stats),
        "@DIV_LUT@": json.dumps(div_lut),
        "@VMIN_MS@": f"{vmin:.4f}",
        "@VMAX_MS@": f"{vmax:.4f}",
        "@DRANGE@": f"{drange:.2f}",
        "@DRANGE_PCT@": f"{drange*100:.0f}",
        "@DIV_RAMP_URI@": ramp_uri(DIV_CMAP),
        "@UNCERTAINTY@": C.UNCERTAINTY_STATEMENT,
    }.items():
        html = html.replace(k, v)
    WEB.mkdir(exist_ok=True)
    out = WEB / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aurora network wind gusts — year-to-year comparison</title>
<style>@LEAFLET_CSS@</style>
<style>
  html, body, #map { height: 100%; margin: 0;
    font: 12px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .panel { background: rgba(255,255,255,.95); padding: 9px 11px;
    border-radius: 6px; box-shadow: 0 1px 5px rgba(0,0,0,.4); color: #0b0b0b; }
  .panel h4 { margin: 0 0 4px; font-size: 12px; }
  .panel select { font: inherit; margin: 0 2px; }
  .panel .presets button { font: 11px system-ui, sans-serif; margin: 4px 3px 0 0;
    padding: 1px 6px; border: 1px solid #c3c2b7; border-radius: 4px;
    background: #fff; cursor: pointer; }
  .panel .presets button:hover { background: #f0efec; }
  .sideA { border-top: 3px solid #2a78d6; }
  .sideB { border-top: 3px solid #eb6834; }
  .readout { min-width: 300px; }
  .readout .big { font-size: 15px; font-weight: 600; }
  .readout .muted, .legendbox .muted { color: #52514e; }
  .readout table { border-collapse: collapse; margin: 3px 0; }
  .readout td { padding: 1px 8px 1px 0; }
  .keydot { display: inline-block; width: 9px; height: 9px; border-radius: 2px;
            margin-right: 4px; vertical-align: baseline; }
  .uncert { margin-top: 6px; padding-top: 5px; border-top: 1px solid #e1e0d9;
            font-style: italic; color: #52514e; max-width: 300px; }
  #chart { margin-top: 6px; }
  #chart svg { display: block; }
  #tip { position: absolute; pointer-events: none; background: #0b0b0b;
    color: #fff; padding: 3px 7px; border-radius: 4px; font-size: 11px;
    display: none; z-index: 1000; white-space: nowrap; }
</style>
</head>
<body>
<div id="map"></div>
<div id="tip"></div>
<script>@LEAFLET_JS@</script>
<script>
'use strict';
const IMGS = @IMGS@, BOUNDS = @BOUNDS@, YEARS = @YEARS@, STATS = @STATS@,
      DIV_LUT = @DIV_LUT@, KMH = 3.6,
      VMIN = @VMIN_MS@, VMAX = @VMAX_MS@, DRANGE = @DRANGE@;
const DOMS = Object.keys(YEARS);
const ALL_YEARS = [...new Set(DOMS.flatMap(d => YEARS[d]))].sort((a,b) => a-b);
const Y0 = ALL_YEARS[0], Y1 = ALL_YEARS[ALL_YEARS.length - 1];
const SIDE_COLOR = {A: '#2a78d6', B: '#eb6834'};

const map = L.map('map');
map.fitBounds([[-46.1, 168.18], [-44.13, 170.8]]);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 17, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// --- data decoding & period averaging ---------------------------------------
const cache = new Map();
async function decode(dom, year) {
  const key = dom + year;
  if (cache.has(key)) return cache.get(key);
  const img = new Image();
  img.src = IMGS[dom][year];
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.width; c.height = img.height;
  const ctx = c.getContext('2d', {willReadFrequently: true});
  ctx.drawImage(img, 0, 0);
  const d = ctx.getImageData(0, 0, c.width, c.height);
  cache.set(key, d);
  return d;
}
async function periodMean(dom, years) {  // mean byte per cell + validity
  const first = await decode(dom, years[0]);
  const n = first.width * first.height;
  const sum = new Float64Array(n);
  for (const y of years) {
    const d = (await decode(dom, y)).data;
    for (let i = 0; i < n; i++) sum[i] += d[i * 4];
  }
  for (let i = 0; i < n; i++) sum[i] /= years.length;
  return {w: first.width, h: first.height, avg: sum, alpha: first.data};
}
const toMs = byte => VMIN + byte / 255 * (VMAX - VMIN);

// --- periods ------------------------------------------------------------------
const sides = {
  A: {from: Y0, to: Math.min(2020, Y1)},
  B: {from: Y1, to: Y1},
};
function sideYears(s, dom) {
  return YEARS[dom].filter(y => y >= s.from && y <= s.to);
}

// --- difference overlay ---------------------------------------------------------
const overlays = {};
let renderSeq = 0;
async function renderDiff() {
  const seq = ++renderSeq;
  for (const dom of DOMS) {
    const ya = sideYears(sides.A, dom), yb = sideYears(sides.B, dom);
    if (!ya.length || !yb.length) continue;
    const [a, b] = await Promise.all([periodMean(dom, ya), periodMean(dom, yb)]);
    if (seq !== renderSeq) return;            // superseded by a newer selection
    const n = a.w * a.h, out = new ImageData(a.w, a.h), o = out.data;
    for (let i = 0; i < n; i++) {
      if (a.alpha[i * 4 + 3] === 0) continue;
      const rel = (toMs(b.avg[i]) - toMs(a.avg[i])) / toMs(a.avg[i]);
      const t = Math.max(-1, Math.min(1, rel / DRANGE));
      const c = DIV_LUT[Math.round((t + 1) / 2 * 255)];
      o[i * 4] = c[0]; o[i * 4 + 1] = c[1]; o[i * 4 + 2] = c[2];
      o[i * 4 + 3] = 200;
    }
    const cv = document.createElement('canvas');
    cv.width = a.w; cv.height = a.h;
    cv.getContext('2d').putImageData(out, 0, 0);
    const url = cv.toDataURL();
    if (overlays[dom]) overlays[dom].setUrl(url);
    else overlays[dom] = L.imageOverlay(url, BOUNDS[dom], {opacity: 1}).addTo(map);
  }
  updateReadout(); updateBands();
}

function periodLabel(s) {
  return s.from === s.to ? String(s.from) : s.from + '–' + s.to;
}
function combinedMean(s) {  // area-weighted across domains, m/s
  let num = 0, den = 0, perDom = {};
  for (const dom of DOMS) {
    const ys = sideYears(s, dom);
    if (!ys.length) continue;
    const m = ys.reduce((t, y) => t + STATS[dom][y].mean_ms, 0) / ys.length;
    const cells = STATS[dom][ys[0]].cells;
    perDom[dom] = m; num += m * cells; den += cells;
  }
  return {all: num / den, perDom};
}

// --- controls ----------------------------------------------------------------
function sideControl(name, position) {
  const ctl = L.control({position});
  ctl.onAdd = () => {
    const s = sides[name];
    const d = L.DomUtil.create('div', 'panel side' + name);
    const opts = f => ALL_YEARS.map(y =>
      `<option value="${y}" ${y === f ? 'selected' : ''}>${y}</option>`).join('');
    d.innerHTML = `<h4>Period ${name}${name === 'A' ? ' (baseline)' : ''}</h4>
      <label>from <select data-k="from">${opts(s.from)}</select></label>
      <label>to <select data-k="to">${opts(s.to)}</select></label>
      <div class="presets">
        <button data-p="norm">1991–2020</button>
        <button data-p="last5">last 5 yrs</button>
        <button data-p="latest">${Y1}</button>
      </div>`;
    L.DomEvent.disableClickPropagation(d);
    const sels = d.querySelectorAll('select');
    const apply = () => {
      let f = +sels[0].value, t = +sels[1].value;
      if (f > t) [f, t] = [t, f];
      s.from = f; s.to = t;
      sels[0].value = f; sels[1].value = t;
      renderDiff();
    };
    sels.forEach(el => el.addEventListener('change', apply));
    d.querySelectorAll('.presets button').forEach(b =>
      b.addEventListener('click', () => {
        const p = b.dataset.p;
        if (p === 'norm') { sels[0].value = Y0; sels[1].value = Math.min(2020, Y1); }
        if (p === 'last5') { sels[0].value = Math.max(Y0, Y1 - 4); sels[1].value = Y1; }
        if (p === 'latest') { sels[0].value = Y1; sels[1].value = Y1; }
        apply();
      }));
    return d;
  };
  return ctl.addTo(map);
}
sideControl('A', 'topleft');
sideControl('B', 'topright');

// --- readout + annual chart ---------------------------------------------------
const CW = 340, CH = 120, ML = 34, MR = 8, MT = 14, MB = 18;
const readoutCtl = L.control({position: 'bottomleft'});
let readoutDiv;
readoutCtl.onAdd = () => {
  readoutDiv = L.DomUtil.create('div', 'panel readout');
  L.DomEvent.disableClickPropagation(readoutDiv);
  readoutDiv.innerHTML = '<h4>Service-area mean p99 gust</h4>' +
    '<div id="numbers"></div>' +
    '<div id="chart"></div>' +
    '<div class="muted">annual, km/h, area-weighted over both domains; ' +
    'shaded bands = selected periods</div>';
  return readoutDiv;
};
readoutCtl.addTo(map);

const series = ALL_YEARS.map(y => {
  let num = 0, den = 0;
  for (const dom of DOMS) {
    if (!STATS[dom][y]) continue;
    num += STATS[dom][y].mean_ms * STATS[dom][y].cells;
    den += STATS[dom][y].cells;
  }
  return {year: y, kmh: num / den * KMH};
});
const vals = series.map(p => p.kmh);
const yLo = Math.floor(Math.min(...vals) / 2) * 2 - 2,
      yHi = Math.ceil(Math.max(...vals) / 2) * 2 + 2;
const X = y => ML + (y - Y0) / (Y1 - Y0) * (CW - ML - MR);
const Y = v => MT + (yHi - v) / (yHi - yLo) * (CH - MT - MB);

function drawChart() {
  const ticks = [];
  for (let v = yLo + 2; v < yHi; v += 4) ticks.push(v);
  const grid = ticks.map(v =>
    `<line x1="${ML}" x2="${CW - MR}" y1="${Y(v)}" y2="${Y(v)}"
       stroke="#e1e0d9" stroke-width="1"/>
     <text x="${ML - 5}" y="${Y(v) + 3}" text-anchor="end" font-size="9"
       fill="#898781">${v}</text>`).join('');
  const xt = ALL_YEARS.filter(y => y % 5 === 0).map(y =>
    `<text x="${X(y)}" y="${CH - 4}" text-anchor="middle" font-size="9"
       fill="#898781">${y}</text>`).join('');
  const path = series.map((p, i) =>
    (i ? 'L' : 'M') + X(p.year).toFixed(1) + ' ' + Y(p.kmh).toFixed(1)).join('');
  document.getElementById('chart').innerHTML =
    `<svg width="${CW}" height="${CH}" role="img"
       aria-label="Annual service-area mean p99 gust">
      <g id="bands"></g>${grid}${xt}
      <line x1="${ML}" x2="${CW - MR}" y1="${Y(yLo)}" y2="${Y(yLo)}"
        stroke="#c3c2b7" stroke-width="1"/>
      <path d="${path}" fill="none" stroke="#2a78d6" stroke-width="2"
        stroke-linejoin="round" stroke-linecap="round"/>
      <circle id="hoverdot" r="4" fill="#2a78d6" stroke="#fff" stroke-width="2"
        style="display:none"/>
      <rect x="${ML}" y="${MT}" width="${CW - ML - MR}" height="${CH - MT - MB}"
        fill="transparent" id="hoverzone"/>
    </svg>`;
  const svg = readoutDiv.querySelector('svg'),
        zone = svg.querySelector('#hoverzone'),
        dot = svg.querySelector('#hoverdot'),
        tip = document.getElementById('tip');
  zone.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect();
    const year = Math.round(Y0 + (e.clientX - r.left - ML) / (CW - ML - MR) * (Y1 - Y0));
    const p = series.find(q => q.year === Math.min(Y1, Math.max(Y0, year)));
    if (!p) return;
    dot.style.display = '';
    dot.setAttribute('cx', X(p.year)); dot.setAttribute('cy', Y(p.kmh));
    tip.style.display = 'block';
    tip.textContent = `${p.year}: ${p.kmh.toFixed(1)} km/h`;
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY - 24) + 'px';
  });
  zone.addEventListener('mouseleave', () => {
    dot.style.display = 'none'; tip.style.display = 'none';
  });
}
function updateBands() {
  const g = readoutDiv.querySelector('#bands');
  if (!g) return;
  g.innerHTML = ['A', 'B'].map(n => {
    const s = sides[n];
    const x0 = X(Math.max(Y0, s.from) - 0.4), x1 = X(Math.min(Y1, s.to) + 0.4);
    return `<rect x="${x0}" y="${MT}" width="${Math.max(2, x1 - x0)}"
      height="${CH - MT - MB}" fill="${SIDE_COLOR[n]}" opacity="0.13"/>
      <text x="${(x0 + x1) / 2}" y="${MT - 3}" text-anchor="middle" font-size="9"
        fill="#52514e">${n}</text>`;
  }).join('');
}
function updateReadout() {
  const a = combinedMean(sides.A), b = combinedMean(sides.B);
  const dk = (b.all - a.all) * KMH, dp = (b.all / a.all - 1) * 100;
  const row = (n, m) => `<tr>
    <td><span class="keydot" style="background:${SIDE_COLOR[n]}"></span>
        ${n} · ${periodLabel(sides[n])}</td>
    <td class="big">${(m.all * KMH).toFixed(1)} km/h</td>
    <td class="muted">Dn ${(m.perDom.dunedin * KMH).toFixed(0)} ·
        Ctl ${(m.perDom.central * KMH).toFixed(0)}</td></tr>`;
  document.getElementById('numbers').innerHTML =
    `<table>${row('A', a)}${row('B', b)}</table>
     <div>B − A: <b>${dk >= 0 ? '+' : ''}${dk.toFixed(1)} km/h</b>
       (${dp >= 0 ? '+' : ''}${dp.toFixed(1)}%)</div>`;
}

// --- legend --------------------------------------------------------------------
const legend = L.control({position: 'bottomright'});
legend.onAdd = () => {
  const d = L.DomUtil.create('div', 'panel legendbox');
  d.innerHTML = `
    <h4>p99 gust: relative difference, B vs A</h4>
    <img src="@DIV_RAMP_URI@" style="width:100%;height:12px">
    <div style="display:flex;justify-content:space-between">
      <span>−@DRANGE_PCT@%</span>
      <span class="muted">0 = no change</span>
      <span>+@DRANGE_PCT@%</span></div>
    <div class="muted" style="max-width:300px;margin-top:4px">
      Red = windier in period B than in period A; blue = calmer. Values
      beyond ±@DRANGE_PCT@% saturate. Multi-year periods = average of annual
      p99 surfaces. Spatial pattern reflects each period's wind-direction mix
      over the (climatological) terrain response; interannual signal is ERA5.
      Map clipped to the Aurora service area + 10 km.</div>
    <div class="uncert">@UNCERTAINTY@</div>`;
  L.DomEvent.disableClickPropagation(d);
  return d;
};
legend.addTo(map);

drawChart();
renderDiff();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
