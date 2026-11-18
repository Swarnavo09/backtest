"""
Build one clean 1-minute NIFTY 50 spot series and save it as data/nifty_1m.parquet.

Sources (public GitHub datasets, cloned into data/raw/ on first run):
  * sandeepkapri/Nifty50-Minute-Data      -> Jan 2015 .. Mar 2024
  * technovusin/nifty50-historical-data   -> Apr 2017 .. today (updated regularly)
The two agree to a median of 0.05 index points where they overlap; the newer one wins.

Usage:  python data/build_data.py
"""
import glob
import os
import subprocess

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
REPOS = ["sandeepkapri/Nifty50-Minute-Data", "technovusin/nifty50-historical-data"]


def clone_sources():
    os.makedirs(RAW, exist_ok=True)
    for r in REPOS:
        dst = os.path.join(RAW, r.split("/")[1])
        if os.path.isdir(dst):
            subprocess.run(["git", "-C", dst, "pull", "-q"], check=False)  # refresh to latest
        else:
            subprocess.run(["git", "clone", "--depth", "1", "-q", f"https://github.com/{r}.git", dst], check=True)


def build():
    a = pd.read_csv(os.path.join(RAW, "Nifty50-Minute-Data", "nifty50_candlestick_data.csv"))
    a.index = pd.to_datetime(a.Date + " " + a.Time, format="%d-%m-%Y %H:%M:%S")
    a = a[["Open", "High", "Low", "Close"]]

    files = sorted(glob.glob(os.path.join(RAW, "nifty50-historical-data", "1min", "*", "*.csv")))
    b = pd.concat([pd.read_csv(f, usecols=[1, 2, 3, 4, 5]) for f in files])
    b.index = pd.to_datetime(b.Timestamp)
    b = b[["Open", "High", "Low", "Close"]]

    df = pd.concat([a[a.index < b.index[0]], b]).sort_index()
    df = df[~df.index.duplicated()].between_time("09:15", "15:29")
    df = df[(df > 0).all(axis=1)]
    # drop partial sessions (e.g. Muhurat trading) - fewer than 300 one-minute bars
    n = df.groupby(df.index.date).size()
    df = df[pd.Index(df.index.date).isin(n[n >= 300].index)]
    out = os.path.join(HERE, "nifty_1m.parquet")
    df.to_parquet(out)
    print(f"saved {out}: {df.index[0]} -> {df.index[-1]}, {len(df):,} bars, {df.index.normalize().nunique()} days")


if __name__ == "__main__":
    clone_sources()
    build()
