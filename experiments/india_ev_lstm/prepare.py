"""
SYNTHETIC-DEMAND EXPERIMENT - step 1: station-hourly -> city-hourly utilization.

Source: india_ev_4cities/ from the incoming datasets.zip (built by its build_real_dataset.py).
Station names/locations are real (OpenStreetMap + web listings); every hourly column
(occupancy, demand, faults, price, weather) is SIMULATED by that script. Nothing produced
here is a real-world observation.

Per city and hour (timestamps are naive local time, India Standard Time, no DST):
    installed_chargers = sum of total_chargers over the city's stations (fixed)
    occupied           = sum of chargers_occupied
    working            = sum of chargers_working        (kept for reference, not a model input)
    demand_vehicles    = sum of demand_vehicles          (simulated vehicles wanting a charger)
    energy_kwh         = sum of energy_kwh
    utilization        = occupied / installed_chargers   ("installed_fixed", as in production)
    is_festival        = 1 if the hour falls in one of the generator's festival windows

Only reads the CSVs (chunked, selected columns). Never runs code from the archive.

Run (from the repo root, using the ml-service environment without changing it):
    uv run --directory ml-service --frozen python -I ../experiments/india_ev_lstm/prepare.py \
        --source <extracted datasets.zip>/india_ev_4cities
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "data"
HOURLY_COLS = ["timestamp", "station_id", "total_chargers", "chargers_working", "chargers_occupied",
               "demand_vehicles", "energy_kwh", "festival"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def aggregate(source: Path) -> tuple[pd.DataFrame, dict]:
    stations = pd.read_csv(source / "stations.csv", usecols=["station_id", "city", "total_chargers"])
    if stations.station_id.duplicated().any():
        raise ValueError("duplicate station_id in stations.csv")
    city_of = stations.set_index("station_id").city
    capacity = stations.groupby("city").total_chargers.sum()

    parts, rows, cap_mismatch = [], 0, 0
    for ch in pd.read_csv(source / "station_hourly.csv", usecols=HOURLY_COLS, chunksize=500_000):
        rows += len(ch)
        ch["city"] = ch.station_id.map(city_of)
        if ch.city.isna().any():
            raise ValueError("hourly rows reference stations missing from stations.csv")
        cap_mismatch += int((ch.total_chargers != ch.station_id.map(stations.set_index("station_id").total_chargers)).sum())
        ch["is_festival"] = ch.festival.notna() & ch.festival.astype(str).str.len().gt(0)
        parts.append(ch.groupby(["city", "timestamp"]).agg(
            occupied=("chargers_occupied", "sum"), working=("chargers_working", "sum"),
            demand_vehicles=("demand_vehicles", "sum"), energy_kwh=("energy_kwh", "sum"),
            is_festival=("is_festival", "max"), n_stations=("station_id", "size")))
    if cap_mismatch:
        raise ValueError(f"{cap_mismatch} hourly rows disagree with stations.csv total_chargers")

    agg = (pd.concat(parts).groupby(level=["city", "timestamp"])
           .agg({"occupied": "sum", "working": "sum", "demand_vehicles": "sum", "energy_kwh": "sum",
                 "is_festival": "max", "n_stations": "sum"}).reset_index())
    agg["timestamp"] = pd.to_datetime(agg.timestamp)
    agg["installed_chargers"] = agg.city.map(capacity).astype(int)
    agg["utilization"] = agg.occupied / agg.installed_chargers
    agg["is_festival"] = agg.is_festival.astype(int)
    agg = agg.sort_values(["city", "timestamp"]).reset_index(drop=True)

    # Integrity: every city has every station in every hour of one contiguous hourly grid.
    n_by_city = stations.city.value_counts()
    if not (agg.n_stations == agg.city.map(n_by_city)).all():
        raise ValueError("some city-hours are missing stations")
    for city, g in agg.groupby("city"):
        expected = pd.date_range(g.timestamp.min(), g.timestamp.max(), freq="h")
        if len(g) != len(expected) or not (g.timestamp.to_numpy() == expected.to_numpy()).all():
            raise ValueError(f"{city}: hourly grid has gaps or duplicates")
    if not agg.utilization.between(0, 1).all():
        raise ValueError("utilization outside [0, 1]")

    info = {
        "station_hourly_rows": rows,
        "stations_per_city": n_by_city.sort_index().to_dict(),
        "installed_chargers_per_city": capacity.sort_index().astype(int).to_dict(),
        "time_range_local": [str(agg.timestamp.min()), str(agg.timestamp.max())],
        "city_hours": len(agg),
    }
    return agg.drop(columns="n_stations"), info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True, help="folder containing india_ev_4cities CSVs")
    args = ap.parse_args()

    agg, info = aggregate(args.source)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "city_hourly.csv"
    agg.to_csv(out_csv, index=False, float_format="%.6f")

    manifest = {
        "WARNING": "SYNTHETIC DEMAND. Hourly occupancy/demand/energy are simulated by the dataset's "
                   "build_real_dataset.py; only the station list is real. Not real-world observations.",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_folder": str(args.source),
        "source_sha256": {f: sha256(args.source / f) for f in ("station_hourly.csv", "stations.csv")},
        "timezone_assumed": "Asia/Kolkata (timestamps are naive; IST has no DST)",
        "target_definition": "utilization = sum(chargers_occupied) / sum(installed total_chargers) per city-hour",
        "capacity_mode": "installed_fixed (charger faults lower 'working' but not the denominator)",
        "output": {"file": "data/city_hourly.csv", "sha256": sha256(out_csv)},
        **info,
    }
    (OUT_DIR / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
