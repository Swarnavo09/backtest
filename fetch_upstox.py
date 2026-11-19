"""Download one year+ of Nifty 50 5-minute candles and daily India VIX from Upstox.

Upstox's v3 historical-candle endpoint is public (no API key) and serves minute
candles back to 2022, one month per request for 5-minute data.

    python fetch_upstox.py                       # last ~13 months
    python fetch_upstox.py 2025-01-01 2026-11-18 # custom range
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

BASE = "https://api.upstox.com/v3/historical-candle"
OUT = Path(__file__).parent / "data"


def get(key: str, unit: str, interval: int, start: date, end: date) -> list:
    url = f"{BASE}/{urllib.parse.quote(key, safe='')}/{unit}/{interval}/{end}/{start}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (backtest script)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["data"]["candles"]
        except Exception as e:  # network hiccup or rate limit: back off and retry
            print(f"  retry {attempt + 1} for {start}..{end}: {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed {url}")


def to_df(candles: list) -> pd.DataFrame:
    df = pd.DataFrame(candles, columns=["Datetime", "Open", "High", "Low", "Close", "Volume", "OI"])
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df.drop(columns="OI").set_index("Datetime").sort_index()


def main() -> None:
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today() - timedelta(days=1)
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else end - timedelta(days=400)
    OUT.mkdir(exist_ok=True)

    parts, s = [], start
    while s <= end:
        e = min(date(s.year + (s.month == 12), s.month % 12 + 1, 1) - timedelta(days=1), end)
        c = get("NSE_INDEX|Nifty 50", "minutes", 5, s, e)
        print(f"Nifty 5m {s} -> {e}: {len(c)} candles")
        parts.append(to_df(c))
        s = e + timedelta(days=1)
        time.sleep(0.4)
    nifty = pd.concat(parts)
    nifty = nifty[~nifty.index.duplicated()].sort_index()
    nifty.to_csv(OUT / "nifty_5m_1y.csv")

    vix = to_df(get("NSE_INDEX|India VIX", "days", 1, start - timedelta(days=10), end))
    vix.index = vix.index.tz_localize(None).normalize()
    vix.to_csv(OUT / "indiavix_1d_1y.csv")
    print(f"saved {len(nifty)} Nifty candles, {len(vix)} VIX days")


if __name__ == "__main__":
    main()
