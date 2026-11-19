"""Download NSE participant-wise open interest (Client / DII / FII / Pro) for every trading day.

NSE publishes the file each evening (usually by ~19:00 IST) at
https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv

    python fetch_participant_oi.py            # all days in data/nifty_5m_5y.csv (+ today if out)
    python fetch_participant_oi.py 2026-11-19 # one day
"""
import io
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "participant_oi.csv"
UA = {"User-Agent": "Mozilla/5.0 (backtest script)"}
COLS = ["fut_idx_long", "fut_idx_short", "fut_stk_long", "fut_stk_short", "call_long", "put_long",
        "call_short", "put_short", "stk_call_long", "stk_put_long", "stk_call_short", "stk_put_short",
        "total_long", "total_short"]


def fetch(d: pd.Timestamp):
    url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                txt = r.read().decode("utf-8", "ignore")
            break
        except Exception as e:
            if "404" in str(e) or attempt == 2:
                return None
            time.sleep(2 + 2 * attempt)
    rows = []
    for line in txt.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if parts and parts[0] in ("Client", "DII", "FII", "Pro"):
            vals = [float(x) for x in parts[1:15]]
            rows.append(dict(date=d.normalize(), who=parts[0], **dict(zip(COLS, vals))))
    return pd.DataFrame(rows) if rows else None


def main():
    if len(sys.argv) > 1:
        days = [pd.Timestamp(sys.argv[1])]
    else:
        n5 = pd.read_csv(ROOT / "data" / "nifty_5m_5y.csv", usecols=[0])
        days = sorted(pd.to_datetime(n5.iloc[:, 0].str[:10]).unique())
    have = set()
    old = None
    if OUT.exists():
        old = pd.read_csv(OUT, parse_dates=["date"])
        have = set(old.date)
    todo = [pd.Timestamp(d) for d in days if pd.Timestamp(d) not in have]
    with ThreadPoolExecutor(6) as ex:
        parts = [x for x in ex.map(fetch, todo) if x is not None]
    allp = pd.concat(([old] if old is not None else []) + parts).sort_values(["date", "who"])
    allp.to_csv(OUT, index=False)
    print(f"{len(parts)} new days; {allp.date.nunique()} days total, last {allp.date.max().date()}")


if __name__ == "__main__":
    main()
