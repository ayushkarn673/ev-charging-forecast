"""
Download charging-session records from the official ACN-Data API (Caltech).

Source : https://ev.caltech.edu/dataset   (API docs: https://ev.caltech.edu/dataset)
Client : request format follows the official acnportal DataClient
         (https://github.com/zach401/acnportal/blob/master/acnportal/acndata/data_client.py)
Cite   : Lee, Z. J., Li, T., & Low, S. H. (2019). ACN-Data: Analysis and Applications of an
         Open EV Charging Dataset. Proc. 10th ACM Int. Conf. on Future Energy Systems (e-Energy '19).

The API token is read from the ACN_API_TOKEN environment variable (or a git-ignored .env
file). It is never written to disk by this script.

Privacy: userID and userInputs are dropped; only the fields needed to build
station-level demand series are kept.

Usage:
    uv run fetch_acn_data.py                    # all three sites, full history
    uv run fetch_acn_data.py --sites caltech jpl
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

API_URL = "https://ev.caltech.edu/api/v1/"
SITES = ("caltech", "jpl", "office001")
PAGE_SIZE = 100  # same page size acnportal uses
KEEP_FIELDS = [
    "_id", "sessionID", "siteID", "clusterID", "stationID", "spaceID",
    "connectionTime", "disconnectTime", "doneChargingTime", "kWhDelivered", "timezone",
]
DATE_FIELDS = ["connectionTime", "disconnectTime", "doneChargingTime"]

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "dataset" / "raw"

log = logging.getLogger("fetch_acn")


def _get(session: requests.Session, url: str, token: str, retries: int = 5) -> dict:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, auth=(token, ""), timeout=60)
            if r.status_code == 401:
                sys.exit("ACN-Data API rejected the token (HTTP 401). Check ACN_API_TOKEN.")
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("Request failed (%s); retrying in %ss", exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _to_iso_utc(value):
    """API dates are RFC 1123 strings in GMT, e.g. 'Wed, 25 Apr 2018 11:08:04 GMT'."""
    if value in (None, ""):
        return None
    return parsedate_to_datetime(value).isoformat()


def fetch_site(site: str, token: str) -> pd.DataFrame:
    http = requests.Session()
    url = f"{API_URL}sessions/{site}?sort=connectionTime&max_results={PAGE_SIZE}"
    payload = _get(http, url, token)
    total = payload.get("_meta", {}).get("total")
    log.info("%s: %s sessions reported by API", site, total)

    rows, page = [], 1
    while True:
        for item in payload["_items"]:
            row = {k: item.get(k) for k in KEEP_FIELDS}
            for f in DATE_FIELDS:
                row[f] = _to_iso_utc(row[f])
            rows.append(row)
        if page % 50 == 0:
            log.info("%s: page %d, %d rows so far", site, page, len(rows))
        nxt = payload.get("_links", {}).get("next")
        if not nxt:
            break
        payload = _get(http, API_URL + nxt["href"], token)
        page += 1

    df = pd.DataFrame(rows, columns=KEEP_FIELDS)
    if total is not None and len(df) != int(total):
        log.warning("%s: downloaded %d rows but API reported %s", site, len(df), total)
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", nargs="+", default=list(SITES), choices=SITES)
    ap.add_argument("--force", action="store_true", help="re-download sites that are already saved")
    args = ap.parse_args()

    token = os.environ.get("ACN_API_TOKEN", "").strip()
    if not token:
        sys.exit("ACN_API_TOKEN is not set. Register at https://ev.caltech.edu/register, then "
                 "set the token as an environment variable or in ml-service/.env")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for site in args.sites:
        out = RAW_DIR / f"acn_{site}_sessions.csv"
        if out.exists() and not args.force:
            log.info("%s: already saved (%s), skipping; use --force to re-download", site, out.name)
            continue
        df = fetch_site(site, token)
        # Write to a temp file first so an interrupted run never leaves a partial site file.
        tmp = out.with_suffix(".csv.part")
        df.to_csv(tmp, index=False)
        tmp.replace(out)
        log.info("%s: saved %d rows -> %s", site, len(df), out.relative_to(ROOT))

    frames = [pd.read_csv(RAW_DIR / f"acn_{s}_sessions.csv", dtype=str)
              for s in SITES if (RAW_DIR / f"acn_{s}_sessions.csv").exists()]
    combined = pd.concat(frames, ignore_index=True)
    out = RAW_DIR / "acn_sessions_raw.csv"
    combined.to_csv(out, index=False)
    log.info("Combined: %d rows -> %s", len(combined), out.relative_to(ROOT))


if __name__ == "__main__":
    main()
