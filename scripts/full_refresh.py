"""Unattended full-pipeline refresh: 30-year ERA5 pull, then re-run every
downstream step with the settings confirmed at Checkpoints 1-6.

Designed to run detached overnight. Logs to outputs/diagnostics/full_refresh.log.
Resumable: the ERA5 fetch skips existing months; if the process dies, just
run it again. WindNinja outputs are cleared first because the per-sector
input speeds change with the new climatology. Does NOT git commit — results
are reviewed before committing.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as C

LOG = C.DIAGNOSTICS / "full_refresh.log"
PY = sys.executable
SCRIPTS = Path(__file__).parent

STEPS = [
    ("ERA5 30-yr pull", ["03_fetch_era5.py", "--all"]),
    ("climatology", ["04_era5_climatology.py"]),
    ("windninja", ["05_run_windninja.py"]),
    ("gust surface", ["06_gust_surface.py"]),
    ("confidence", ["07_confidence_layer.py"]),
    ("zones", ["08_zones.py", "--classify", "jenks"]),
    ("arrows", ["09_arrows.py"]),
    ("lightning", ["11_lightning_density.py"]),  # self-skips if source absent
    ("webmap", ["10_build_webmap.py"]),
]


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    C.DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    log("=== full refresh started ===")

    # New climatology -> new input speeds -> WindNinja must re-run.
    cleared = 0
    for f in C.WINDNINJA_DIR.glob("*/*_vel.asc"):
        f.unlink()
        cleared += 1
    log(f"cleared {cleared} cached WindNinja outputs")

    for name, args in STEPS:
        log(f"--- {name}: {' '.join(args)}")
        t0 = time.time()
        proc = subprocess.run([PY, str(SCRIPTS / args[0]), *args[1:]],
                              capture_output=True, text=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(proc.stdout[-4000:] + "\n")
            if proc.stderr.strip():
                fh.write("--- stderr ---\n" + proc.stderr[-4000:] + "\n")
        if proc.returncode != 0:
            log(f"FAILED at '{name}' (exit {proc.returncode}) after "
                f"{(time.time()-t0)/60:.1f} min — rerun this script to resume")
            sys.exit(proc.returncode)
        log(f"    ok ({(time.time()-t0)/60:.1f} min)")

    log("=== full refresh complete — review before committing ===")


if __name__ == "__main__":
    main()
