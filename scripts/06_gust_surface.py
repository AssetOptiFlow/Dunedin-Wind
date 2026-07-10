"""Combine WindNinja speed-up multipliers with the ERA5 gust climatology into
the 500 m gust exposure surface.

  gust99(cell) = sum_s w_s * mult_s(cell) * era5_gust99_s

where w_s = sector frequency among top-decile gust hours (normalised), so the
weighting reflects gust-bearing directions rather than calm-hour frequencies.
Also writes a max-over-sectors "worst case" diagnostic surface.

AS/NZS 1170.2 is used ONLY as a plausibility band (see asnzs_sanity.md output);
it never classifies or calibrates anything.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C
from _util import reproject_to_wgs84

GUST_DIR = C.OUTPUTS / "gust"


def main():
    clim = json.loads((C.OUTPUTS / "era5_climatology.json").read_text())
    sectors = clim["sectors"]
    w = np.array([s["freq_top_decile_gust"] for s in sectors])
    w = w / w.sum()
    g99 = np.array([s["gust_p99_ms"] for s in sectors])

    mults, prof = [], None
    for s in sectors:
        with rasterio.open(C.OUTPUTS / "windninja" / f"mult_{s['sector']}.tif") as src:
            mults.append(src.read(1))
            prof = prof or src.profile.copy()
    mults = np.stack(mults)  # (8, H, W)

    weighted = np.einsum("s,shw,s->hw", w, mults, g99)
    worst = (mults * g99[:, None, None]).max(axis=0)

    GUST_DIR.mkdir(parents=True, exist_ok=True)
    prof.update(dtype="float32")
    for arr, name in [(weighted, "gust99_500m"), (worst, "gust99_worstcase_500m")]:
        p = GUST_DIR / f"{name}.tif"
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(arr.astype("float32"), 1)
        reproject_to_wgs84(p, GUST_DIR / f"{name}_wgs84.tif")
    print(f"gust99 weighted: {np.nanmin(weighted):.1f}..{np.nanmax(weighted):.1f} m/s "
          f"(mean {np.nanmean(weighted):.1f})")
    print(f"gust99 worst-case: {np.nanmin(worst):.1f}..{np.nanmax(worst):.1f} m/s")

    # --- AS/NZS 1170.2 plausibility band (sanity only, never classification) --
    # ERA5+WindNinja p99 hourly gust is a much more frequent event than the
    # AS/NZS design gust (V_R at 1/500 AEP ~ 45 m/s for southern NZ), so the
    # surface must sit WELL BELOW design values; the terrain-category gust
    # multiplier spread (Mz,cat ~0.75-1.10, lee multipliers to ~1.35) bounds
    # how much spatial variation is credible.
    ratio = float(np.nanmax(weighted) / max(np.nanmin(weighted), 1e-6))
    lines = [
        "# AS/NZS 1170.2 plausibility check (sanity bound only)",
        "",
        f"- Weighted p99 gust surface range: {np.nanmin(weighted):.1f}-"
        f"{np.nanmax(weighted):.1f} m/s (mean {np.nanmean(weighted):.1f}).",
        f"- Southern NZ design gust (V_500) is ~45 m/s: surface max "
        f"{'OK (below design)' if np.nanmax(weighted) < 45 else 'SUSPECT (exceeds design gust!)'}.",
        f"- Max/min spatial ratio {ratio:.2f} vs credible AS/NZS terrain+lee "
        f"multiplier spread ~{1.35/0.75:.2f}: "
        f"{'OK' if ratio <= 2.2 else 'wide - inspect multiplier clipping'}.",
        "",
        "This check never classifies zones; see README uncertainty statement.",
    ]
    (C.DIAGNOSTICS / "asnzs_sanity.md").write_text("\n".join(lines))
    print("\n".join(lines[2:]))

    fig, ax = plt.subplots(figsize=(11, 6))
    im = ax.imshow(weighted, cmap="YlOrRd")
    ax.set_title("p99 gust exposure surface (m/s, 500 m, sector-weighted)")
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(C.DIAGNOSTICS / "quicklooks" / "gust99_500m.png", dpi=120,
                bbox_inches="tight")
    print("done")


if __name__ == "__main__":
    main()
