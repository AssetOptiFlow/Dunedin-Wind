"""Build the station-based year-comparison webmap (webmap_compare/index.html).

Shows the 7 reference stations as markers coloured by the relative change in
MEAN DAILY MAX GUST between two user-chosen periods (B vs A, diverging
blue-0-red, fixed range). Clicking a station opens a full A-vs-B comparison:
highest gust (+date), mean daily max, p99, mean, days >= 90/120 km/h, and an
overlaid direction rose of strong-gust hours. A service-area annual chart +
readout give whole-network context.

All station values are ERA5 model estimates at the nearest 0.25-deg grid
cell (from 16_station_yearly_stats.py) — NOT station observations; the page
says so. Periods aggregate client-side (max over years for records, means
otherwise), so any span works offline from one self-contained file.

Standalone read-only build; rerun after 14 (chart stats) + 16 (station
stats) whenever new years land.
"""
import base64
import io
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

REPO = C.REPO
IN = REPO / "outputs_compare"
WEB = REPO / "webmap_compare"
DIV_CMAP = "RdBu_r"   # red = windier in B, blue = calmer, white ~ no change


def ramp_uri(cmap):
    grad = np.tile(np.linspace(0, 1, 256), (18, 1))
    rgba = (colormaps[cmap](grad) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def marker_range(stations):
    """Fixed diverging range for marker colour: worst single-year-pair
    relative difference in mean-daily-max across stations, rounded UP to 5%."""
    worst = 0.0
    for st in stations:
        mdm = [y["mdm_ms"] for y in st["years"].values()]
        for a, b in combinations(mdm, 2):
            worst = max(worst, abs(b - a) / a)
    return float(np.ceil(worst * 20) / 20)


def main():
    yearly = json.loads((IN / "yearly_stats.json").read_text())
    station = json.loads((IN / "station_yearly_stats.json").read_text())

    side_stats = {dom: {str(y): {"mean_ms": v["clip_mean_ms"],
                                 "cells": v["clip_cells"]}
                        for y, v in yearly["domains"][dom]["years"].items()}
                  for dom in yearly["domains"]}

    drange = marker_range(station["stations"])
    div_lut = (colormaps[DIV_CMAP](np.linspace(0, 1, 256))[:, :3] * 255) \
        .astype(int).tolist()
    print(f"{len(station['stations'])} stations; "
          f"marker range ±{drange*100:.0f}% (mean daily max)")

    vendor = REPO / "webmap" / "vendor"
    html = TEMPLATE
    for k, v in {
        "@LEAFLET_CSS@": (vendor / "leaflet.css").read_text(encoding="utf-8"),
        "@LEAFLET_JS@": (vendor / "leaflet.js").read_text(encoding="utf-8"),
        "@STATIONS@": json.dumps(station["stations"]),
        "@SECTORS@": json.dumps(station["sectors"]),
        "@STATS@": json.dumps(side_stats),
        "@DIV_LUT@": json.dumps(div_lut),
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
  .stpop { font: 12px/1.5 system-ui, sans-serif; }
  .stpop h3 { margin: 0 0 1px; font-size: 13px; }
  .stpop .sub { color: #52514e; margin-bottom: 5px; }
  .stpop table { border-collapse: collapse; width: 100%; }
  .stpop th, .stpop td { text-align: right; padding: 1px 4px 1px 10px;
    font-weight: normal; white-space: nowrap; }
  .stpop th:first-child, .stpop td:first-child { text-align: left;
    padding-left: 0; }
  .stpop thead th { color: #52514e; border-bottom: 1px solid #e1e0d9; }
  .stpop td.delta { font-weight: 600; }
  .stpop .date { color: #52514e; font-size: 10px; }
  .stpop .rosecap { color: #52514e; margin-top: 4px; }
  .leaflet-popup-content { margin: 12px 14px; }
</style>
</head>
<body>
<div id="map"></div>
<div id="tip"></div>
<script>@LEAFLET_JS@</script>
<script>
'use strict';
const STATIONS = @STATIONS@, SECTORS = @SECTORS@, STATS = @STATS@,
      DIV_LUT = @DIV_LUT@, DRANGE = @DRANGE@, KMH = 3.6;
const DOMS = Object.keys(STATS);
const ALL_YEARS = [...new Set(DOMS.flatMap(d => Object.keys(STATS[d])))]
  .map(Number).sort((a, b) => a - b);
const Y0 = ALL_YEARS[0], Y1 = ALL_YEARS[ALL_YEARS.length - 1];
const SIDE_COLOR = {A: '#2a78d6', B: '#eb6834'};

const map = L.map('map');
map.fitBounds([[-46.1, 168.18], [-44.13, 170.8]]);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 17, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// --- periods -------------------------------------------------------------------
const sides = {
  A: {from: Y0, to: Math.min(2020, Y1)},
  B: {from: Y1, to: Y1},
};
function sideYears(s, st) {
  return Object.keys(st.years).map(Number)
    .filter(y => y >= s.from && y <= s.to).sort((a, b) => a - b);
}
function periodLabel(s) {
  return s.from === s.to ? String(s.from) : s.from + '–' + s.to;
}

// --- station aggregation ---------------------------------------------------------
const mean = a => a.reduce((t, v) => t + v, 0) / a.length;
function agg(st, side) {
  const ys = sideYears(sides[side], st);
  if (!ys.length) return null;
  const Y = ys.map(y => st.years[y]);
  const iMax = Y.reduce((best, y, i) => y.max_ms > Y[best].max_ms ? i : best, 0);
  return {
    years: ys,
    max_ms: Y[iMax].max_ms, max_date: Y[iMax].max_date,
    mdm_ms: mean(Y.map(y => y.mdm_ms)),
    p99_ms: mean(Y.map(y => y.p99_ms)),
    mean_ms: mean(Y.map(y => y.mean_ms)),
    d90: mean(Y.map(y => y.d90)),
    d120: mean(Y.map(y => y.d120)),
    rose: SECTORS.map((_, i) => mean(Y.map(y => y.rose[i]))),
  };
}

// --- rose SVG (A = blue outline, B = orange fill) --------------------------------
function wedge(cx, cy, r, centreDeg) {
  const a0 = (centreDeg - 20) * Math.PI / 180, a1 = (centreDeg + 20) * Math.PI / 180;
  const x = a => (cx + r * Math.sin(a)).toFixed(1),
        y = a => (cy - r * Math.cos(a)).toFixed(1);
  return `M${cx} ${cy} L${x(a0)} ${y(a0)} A${r} ${r} 0 0 1 ${x(a1)} ${y(a1)} Z`;
}
function roseSvg(ra, rb) {
  const S = 118, cx = S / 2, cy = S / 2, R = S / 2 - 13;
  const fmax = Math.max(...ra, ...rb, 0.01);
  let out = `<svg width="${S}" height="${S}">`;
  out += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#e1e0d9"/>`;
  [['N', cx, 9], ['S', cx, S - 2]].forEach(([t, x, y]) =>
    out += `<text x="${x}" y="${y}" text-anchor="middle" font-size="9"
      fill="#898781">${t}</text>`);
  [['W', 4, cy + 3], ['E', S - 4, cy + 3]].forEach(([t, x, y]) =>
    out += `<text x="${x}" y="${y}" text-anchor="middle" font-size="9"
      fill="#898781">${t}</text>`);
  rb.forEach((f, i) => { if (f > 0) out += `<path
    d="${wedge(cx, cy, R * f / fmax, i * 45)}" fill="${SIDE_COLOR.B}"
    opacity="0.45"/>`; });
  ra.forEach((f, i) => { if (f > 0) out += `<path
    d="${wedge(cx, cy, R * f / fmax, i * 45)}" fill="none"
    stroke="${SIDE_COLOR.A}" stroke-width="1.8"/>`; });
  return out + '</svg>';
}

// --- markers + popups --------------------------------------------------------------
const kmh = (ms, dp = 0) => (ms * KMH).toFixed(dp);
function popupHtml(st) {
  const a = agg(st, 'A'), b = agg(st, 'B');
  if (!a || !b) return `<div class="stpop"><h3>${st.name}</h3>no data in range</div>`;
  const dmy = iso => { const [y, m, d] = iso.split('-');
    return `${+d} ${'JanFebMarAprMayJunJulAugSepOctNovDec'.substr((m-1)*3, 3)} ${y}`; };
  const sgn = v => (v >= 0 ? '+' : '') + v;
  const rows = [
    ['Highest gust',
     `${kmh(a.max_ms)} <span class="date">${dmy(a.max_date)}</span>`,
     `${kmh(b.max_ms)} <span class="date">${dmy(b.max_date)}</span>`,
     sgn(kmh(b.max_ms - a.max_ms)) + ' km/h'],
    ['Mean daily max', kmh(a.mdm_ms, 1), kmh(b.mdm_ms, 1),
     sgn(((b.mdm_ms / a.mdm_ms - 1) * 100).toFixed(1)) + '%'],
    ['p99 hourly gust', kmh(a.p99_ms, 1), kmh(b.p99_ms, 1),
     sgn(kmh(b.p99_ms - a.p99_ms, 1)) + ' km/h'],
    ['Mean hourly gust', kmh(a.mean_ms, 1), kmh(b.mean_ms, 1),
     sgn(kmh(b.mean_ms - a.mean_ms, 1)) + ' km/h'],
    ['Days ≥ 90 km/h /yr', a.d90.toFixed(1), b.d90.toFixed(1),
     sgn((b.d90 - a.d90).toFixed(1))],
    ['Days ≥ 120 km/h /yr', a.d120.toFixed(1), b.d120.toFixed(1),
     sgn((b.d120 - a.d120).toFixed(1))],
  ].map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td>
     <td class="delta">${r[3]}</td></tr>`).join('');
  return `<div class="stpop">
    <h3>${st.name}</h3>
    <div class="sub">${st.domain} · ERA5 cell (${st.grid_lat.toFixed(2)},
      ${st.grid_lon.toFixed(2)}) — model values, not observations</div>
    <table><thead><tr><th></th>
      <th><span class="keydot" style="background:${SIDE_COLOR.A}"></span>A ·
        ${periodLabel(sides.A)}</th>
      <th><span class="keydot" style="background:${SIDE_COLOR.B}"></span>B ·
        ${periodLabel(sides.B)}</th><th>Δ (B−A)</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
      ${roseSvg(a.rose, b.rose)}
      <div class="rosecap">direction of strong-gust hours
        (≥ ${kmh(st.strong_thr_ms)} km/h, this station's all-years p90).<br>
        <span style="color:${SIDE_COLOR.A}">— A outline</span>,
        <span style="color:${SIDE_COLOR.B}">■ B fill</span>.
        Units: km/h${a.years.length > 1 || b.years.length > 1
          ? '; multi-year periods: records = max over years, others = annual means'
          : ''}.</div></div></div>`;
}

function markerColor(st) {
  const a = agg(st, 'A'), b = agg(st, 'B');
  if (!a || !b) return '#898781';
  const t = Math.max(-1, Math.min(1, (b.mdm_ms / a.mdm_ms - 1) / DRANGE));
  const c = DIV_LUT[Math.round((t + 1) / 2 * 255)];
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
const markers = {};
for (const st of STATIONS) {
  markers[st.name] = L.circleMarker([st.lat, st.lon], {
    radius: 10, color: '#222', weight: 1.5, fillOpacity: 0.95,
    fillColor: markerColor(st),
  }).addTo(map)
    .bindTooltip(st.name, {direction: 'top', offset: [0, -8]})
    .bindPopup(() => popupHtml(st), {maxWidth: 360});
}
function refresh() {
  for (const st of STATIONS) {
    markers[st.name].setStyle({fillColor: markerColor(st)});
    if (markers[st.name].isPopupOpen()) markers[st.name].getPopup()
      .setContent(popupHtml(st));
  }
  updateReadout(); updateBands();
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
      refresh();
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
    'shaded bands = selected periods. Click a station for details.</div>';
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
function combinedMean(s) {
  let num = 0, den = 0, perDom = {};
  for (const dom of DOMS) {
    const ys = ALL_YEARS.filter(y => STATS[dom][y] && y >= s.from && y <= s.to);
    if (!ys.length) continue;
    const m = mean(ys.map(y => STATS[dom][y].mean_ms));
    const cells = STATS[dom][ys[0]].cells;
    perDom[dom] = m; num += m * cells; den += cells;
  }
  return {all: num / den, perDom};
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
    <h4>Station change: mean daily max gust, B vs A</h4>
    <img src="@DIV_RAMP_URI@" style="width:100%;height:12px">
    <div style="display:flex;justify-content:space-between">
      <span>−@DRANGE_PCT@%</span>
      <span class="muted">0 = no change</span>
      <span>+@DRANGE_PCT@%</span></div>
    <div class="muted" style="max-width:300px;margin-top:4px">
      Marker colour = relative change in mean daily-max gust between the
      selected periods (red = windier in B). Click a station for the full
      comparison: highest gust, p99, strong-gust days, direction rose.
      Values are ERA5 model estimates at each station's nearest 0.25°
      grid cell (~25 km) — NOT station observations. Days are NZST.</div>
    <div class="uncert">@UNCERTAINTY@</div>`;
  L.DomEvent.disableClickPropagation(d);
  return d;
};
legend.addTo(map);

drawChart();
refresh();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
