#!/usr/bin/env python3
"""
Fetches latest Nifty 50 daily OHLC data and appends to the simulator data file.
Primary: NSE India API. Fallback: Yahoo Finance (yfinance).
Runs daily at 10 PM via launchd.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "NIFTY_FUT_2022_2026.json")
LOG_FILE = os.path.join(DATA_DIR, "fetch.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def load_existing():
    if not os.path.exists(DATA_FILE):
        log.error(f"Data file not found: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE) as f:
        data = json.load(f)
    log.info(f"Loaded {len(data)} existing records from {DATA_FILE}")
    return data


def get_last_date(data):
    if not data:
        return datetime(2022, 1, 1)
    last = data[-1]["date"][:10]
    return datetime.strptime(last, "%Y-%m-%d")


def fetch_from_nse(from_date, to_date):
    """Fetch Nifty 50 index history from NSE India API."""
    import httpx
    import time

    log.info(f"Trying NSE API: {from_date.strftime('%d-%m-%Y')} to {to_date.strftime('%d-%m-%Y')}")

    try:
        with httpx.Client(headers=NSE_HEADERS, follow_redirects=True, timeout=30) as client:
            # Warm up session cookies
            resp = client.get("https://www.nseindia.com")
            if resp.status_code != 200:
                log.warning(f"NSE homepage returned {resp.status_code}")
            time.sleep(2)

            # Fetch index history
            url = "https://www.nseindia.com/api/historical/indicesHistory"
            params = {
                "indexType": "NIFTY 50",
                "from": from_date.strftime("%d-%m-%Y"),
                "to": to_date.strftime("%d-%m-%Y"),
            }
            resp = client.get(url, params=params)

            if resp.status_code != 200:
                log.warning(f"NSE API returned {resp.status_code}")
                return None

            body = resp.json()
            rows = body.get("data", [])
            if not rows:
                log.warning("NSE API returned empty data")
                return None

            records = []
            for row in rows:
                try:
                    dt = datetime.strptime(row["HistoricalDate"], "%d %b %Y")
                    records.append({
                        "date": dt.strftime("%Y-%m-%dT00:00:00+05:30"),
                        "open": float(row["OPEN"].replace(",", "")),
                        "high": float(row["HIGH"].replace(",", "")),
                        "low": float(row["LOW"].replace(",", "")),
                        "close": float(row["CLOSE"].replace(",", "")),
                        "volume": int(float(row.get("VOLUME", "0").replace(",", ""))),
                        "oi": 0,
                    })
                except (KeyError, ValueError) as e:
                    log.warning(f"Skipping row: {e}")
                    continue

            records.sort(key=lambda r: r["date"])
            log.info(f"NSE API returned {len(records)} records")
            return records

    except Exception as e:
        log.warning(f"NSE API failed: {e}")
        return None


def fetch_from_yfinance(from_date, to_date):
    """Fallback: fetch Nifty 50 from Yahoo Finance."""
    log.info(f"Trying Yahoo Finance: {from_date} to {to_date}")

    try:
        import yfinance as yf

        ticker = yf.Ticker("^NSEI")
        df = ticker.history(
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + timedelta(days=1)).strftime("%Y-%m-%d"),
        )

        if df.empty:
            log.warning("yfinance returned empty data")
            return None

        records = []
        for idx, row in df.iterrows():
            dt = idx.to_pydatetime()
            records.append({
                "date": dt.strftime("%Y-%m-%dT00:00:00+05:30"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
                "oi": 0,
            })

        records.sort(key=lambda r: r["date"])
        log.info(f"yfinance returned {len(records)} records")
        return records

    except Exception as e:
        log.warning(f"yfinance failed: {e}")
        return None


def merge_and_save(existing, new_records):
    """Deduplicate by date, sort, and save."""
    seen = {}
    for r in existing:
        key = r["date"][:10]
        seen[key] = r
    added = 0
    for r in new_records:
        key = r["date"][:10]
        if key not in seen:
            seen[key] = r
            added += 1
    merged = sorted(seen.values(), key=lambda r: r["date"])
    with open(DATA_FILE, "w") as f:
        json.dump(merged, f)
    log.info(f"Saved {len(merged)} total records ({added} new) to {DATA_FILE}")
    return added


def main():
    log.info("=" * 50)
    log.info("Nifty 50 daily fetch started")

    existing = load_existing()
    last_date = get_last_date(existing)
    from_date = last_date + timedelta(days=1)
    to_date = datetime.now()

    if from_date.date() > to_date.date():
        log.info("Already up to date, nothing to fetch")
        return

    log.info(f"Fetching data from {from_date.date()} to {to_date.date()}")

    # Try NSE first, fallback to yfinance
    new_records = fetch_from_nse(from_date, to_date)
    if not new_records:
        log.info("NSE failed, falling back to Yahoo Finance")
        new_records = fetch_from_yfinance(from_date, to_date)

    if not new_records:
        log.error("Both sources failed. No data fetched.")
        return

    added = merge_and_save(existing, new_records)
    if added > 0:
        log.info(f"Successfully added {added} new trading day(s)")
        git_push(added)
    else:
        log.info("No new trading days found (weekend/holiday?)")


def git_push(added):
    """Auto-commit and push updated data to GitHub so Streamlit Cloud redeploys."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(["git", "add", "data/NIFTY_FUT_2022_2026.json"], cwd=repo_dir, check=True)
        msg = f"data: +{added} trading day(s) [{datetime.now().strftime('%Y-%m-%d')}]"
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, check=True)
        log.info(f"Pushed to GitHub: {msg}")
    except subprocess.CalledProcessError as e:
        log.warning(f"Git push failed: {e}")


if __name__ == "__main__":
    main()
