"""Nifty option-chain open interest (EOD) from NSE bhavcopies, nearest 2 expiries, all strikes.

    python fetch_oi.py   -> data/nifty_oi.csv.gz  (date, expiry, strike, type, oi)
"""
import io, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

import fetch_bhav as FB

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "nifty_oi.csv.gz"


def fetch(d):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(FB.url(d), headers=FB.UA), timeout=40) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            raw = pd.read_csv(z.open(z.namelist()[0])); break
        except Exception:
            if attempt == 2: return None
            time.sleep(3)
    if "TckrSymb" in raw.columns:
        x = raw[(raw.TckrSymb == "NIFTY") & (raw.FinInstrmTp == "IDO")]
        x = pd.DataFrame({"expiry": pd.to_datetime(x.XpryDt), "strike": x.StrkPric, "type": x.OptnTp, "oi": x.OpnIntrst})
    else:
        x = raw[(raw.SYMBOL == "NIFTY") & (raw.INSTRUMENT == "OPTIDX")]
        x = pd.DataFrame({"expiry": pd.to_datetime(x.EXPIRY_DT, format="%d-%b-%Y"), "strike": x.STRIKE_PR,
                          "type": x.OPTION_TYP, "oi": x.OPEN_INT})
    exps = sorted(e for e in x.expiry.unique() if e >= d)[:2]
    x = x[x.expiry.isin(exps)].copy(); x.insert(0, "date", d)
    return x


def main():
    n5 = pd.read_csv(ROOT / "data" / "nifty_5m_5y.csv", usecols=[0])
    days = sorted(pd.to_datetime(n5.iloc[:, 0].str[:10]).unique())
    with ThreadPoolExecutor(6) as ex:
        parts = [p for p in ex.map(fetch, [pd.Timestamp(d) for d in days]) if p is not None]
    pd.concat(parts).to_csv(OUT, index=False)
    print(len(parts), "days")


if __name__ == "__main__":
    main()
