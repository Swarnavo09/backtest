"""Download NSE F&O bhavcopies and keep Nifty option rows (NEXP nearest expiries, default 2).

Gives real daily open/high/low/close for every Nifty option strike, used to check
the option-pricing model and to price spreads with real premiums.

    python fetch_bhav.py            # trading days taken from data/nifty_5m_5y.csv
"""
import io
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
import os
NEXP = int(os.environ.get("NEXP", "2"))
SYM = os.environ.get("SYM", "NIFTY")
OUT = ROOT / "data" / ((("nifty_opt_bhav.csv.gz" if NEXP == 2 else f"nifty_opt_bhav_{NEXP}exp.csv.gz")) if SYM == "NIFTY" else f"{SYM.lower()}_opt_bhav_{NEXP}exp.csv.gz")
UA = {"User-Agent": "Mozilla/5.0 (backtest script)"}
NEW_FROM = pd.Timestamp("2024-07-08")   # NSE switched to the UDiFF bhavcopy format


def url(d: pd.Timestamp) -> str:
    if d >= NEW_FROM:
        return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d:%Y}/"
            f"{d.strftime('%b').upper()}/fo{d.strftime('%d%b%Y').upper()}bhav.csv.zip")


def fetch(d: pd.Timestamp) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url(d), headers=UA), timeout=40) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            raw = pd.read_csv(z.open(z.namelist()[0]))
            break
        except Exception as e:
            if attempt == 2:
                print(f"{d.date()}: {e}")
                return None
            time.sleep(2 + 3 * attempt)
    if "TckrSymb" in raw.columns:      # new format
        x = raw[(raw.TckrSymb == SYM) & (raw.FinInstrmTp == "IDO")]
        x = pd.DataFrame({"expiry": pd.to_datetime(x.XpryDt), "strike": x.StrkPric, "type": x.OptnTp,
                          "open": x.OpnPric, "high": x.HghPric, "low": x.LwPric, "close": x.ClsPric,
                          "settle": x.SttlmPric, "volume": x.TtlTradgVol, "under": x.UndrlygPric})
    else:
        x = raw[(raw.SYMBOL == SYM) & (raw.INSTRUMENT == "OPTIDX")]
        x = pd.DataFrame({"expiry": pd.to_datetime(x.EXPIRY_DT, format="%d-%b-%Y"), "strike": x.STRIKE_PR,
                          "type": x.OPTION_TYP, "open": x.OPEN, "high": x.HIGH, "low": x.LOW,
                          "close": x.CLOSE, "settle": x.SETTLE_PR, "volume": x.CONTRACTS, "under": float("nan")})
    exps = sorted(e for e in x.expiry.unique() if e >= d)[:NEXP]
    x = x[x.expiry.isin(exps)].copy()
    x.insert(0, "date", d)
    return x


def main():
    n5 = pd.read_csv(ROOT / "data" / "nifty_5m_5y.csv", usecols=[0])
    days = sorted(pd.to_datetime(n5.iloc[:, 0].str[:10]).unique())
    have = set()
    if OUT.exists():
        old = pd.read_csv(OUT, parse_dates=["date", "expiry"])
        have = set(old.date.unique())
    parts = [old] if have else []
    todo = [pd.Timestamp(d) for d in days if pd.Timestamp(d) not in have]
    print(f"{len(todo)} days to fetch")
    from concurrent.futures import ThreadPoolExecutor
    for k in range(0, len(todo), 120):              # 6 at a time, checkpoint every 120 days
        batch = todo[k:k + 120]
        with ThreadPoolExecutor(6) as ex:
            parts.extend(x for x in ex.map(fetch, batch) if x is not None)
        pd.concat(parts).to_csv(OUT, index=False)
        print(f"{k + len(batch)}/{len(todo)} up to {batch[-1].date()}", flush=True)
    print("done")


if __name__ == "__main__":
    main()
