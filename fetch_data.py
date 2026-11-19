"""Download Nifty 50 intraday candles and India VIX from Yahoo Finance.

Yahoo keeps only the last ~60 days of 5-minute and 15-minute candles, so run
this regularly and keep the CSVs if you want a longer history over time.

    python fetch_data.py
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).parent / "data"


def _save(df: pd.DataFrame, name: str) -> None:
    if df.empty:
        print(f"{name}: no data returned")
        return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    path = OUT / name
    if path.exists():  # merge with what we already have so history grows
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        df = pd.concat([old, df])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_csv(path)
    print(f"{name}: {len(df)} rows, {df.index.min()} -> {df.index.max()}")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for interval in ("5m", "15m"):
        df = yf.download("^NSEI", interval=interval, period="60d",
                         progress=False, auto_adjust=False)
        _save(df, f"nifty_{interval}.csv")
    vix = yf.download("^INDIAVIX", period="2y", progress=False, auto_adjust=False)
    _save(vix, "indiavix_1d.csv")


if __name__ == "__main__":
    main()
