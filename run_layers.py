"""Weekly -> daily -> 15-minute layering on the Mon/Tue/Thu strategy.

Ideal layers (not buildable in AlgoRooms): this week's candle colour (price vs week open), today's candle colour.
Buildable layers: EMAs on 1-hour candles (35 one-hour candles ~ 1 week, 7 ~ 1 day).

    python run_layers.py   -> results/layers.json, results/layers_grid.csv
"""
import json
from datetime import time
import numpy as np, pandas as pd
import run_tune as U, run_v2 as R, run_ar_filters as AF
from strategy import ema

U._init()
df0 = U._G["base"]
idx = df0.index
b5 = AF._b5
h = b5.resample("60min", offset="15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
close_ts = [min(t + pd.Timedelta(minutes=60), t.normalize() + pd.Timedelta(hours=15, minutes=30)) for t in h.index]
sig_close = idx + pd.Timedelta(minutes=15)


def onbars(series):
    s = pd.Series(np.asarray(series, float), index=pd.DatetimeIndex(close_ts))
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(sig_close)).ffill().reindex(sig_close).values


hc = h.Close
E_ = {n: ema(hc, n) for n in (7, 21, 35, 63, 70, 147, 175, 350)}
wk = pd.Series(idx.tz_localize(None).to_period("W-SUN").astype(str), index=idx)
wopen = df0.Open.groupby(wk).transform("first").values
dopen = df0.Open.groupby(idx.date).transform("first").values
c = df0.Close.values

WEEK = {   # (bull mask, bear mask)
    "none": None,
    "IDEAL: price above/below this week's open": (c > wopen, c < wopen),
    "1H EMA175 vs EMA350 (weekly EMA 5/10)": (onbars(E_[175] - E_[350]) > 0, onbars(E_[175] - E_[350]) < 0),
    "1H close vs EMA350 (weekly EMA 10)": (onbars(hc - E_[350]) > 0, onbars(hc - E_[350]) < 0),
    "1H close vs EMA175 (weekly EMA 5)": (onbars(hc - E_[175]) > 0, onbars(hc - E_[175]) < 0),
}
DAY = {
    "none": None,
    "IDEAL: price above/below today's open": (c > dopen, c < dopen),
    "1H EMA63 vs EMA147 (daily EMA 9/21)": (onbars(E_[63] - E_[147]) > 0, onbars(E_[63] - E_[147]) < 0),
    "1H EMA21 vs EMA63 (daily EMA 3/9)": (onbars(E_[21] - E_[63]) > 0, onbars(E_[21] - E_[63]) < 0),
    "1H close vs EMA63 (daily EMA 9)": (onbars(hc - E_[63]) > 0, onbars(hc - E_[63]) < 0),
    "1H close vs EMA35 (daily EMA 5)": (onbars(hc - E_[35]) > 0, onbars(hc - E_[35]) < 0),
    "1H close vs EMA7 (about today's trend)": (onbars(hc - E_[7]) > 0, onbars(hc - E_[7]) < 0),
}


def run(w, d, lots, skip={2, 4, 5, 6}):
    df = df0.copy()
    for m in (WEEK[w], DAY[d]):
        if m is not None:
            df["bull"] &= m[0]; df["bear"] &= m[1]
    U._G["base"] = df
    try:
        r = U.simulate("none", time(9, 30), time(13, 30), skip, lots)
    finally:
        U._G["base"] = df0
    return r


def summ(r):
    r = r.sort_values("entry_ts")
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    eq = r.net.cumsum(); dd = (eq - eq.cummax().clip(lower=0)).min()
    return dict(trades=len(r), win=round(100 * (r.net > 0).mean(), 1), train=round(r[d <= R.TRAIN_END].net.sum()),
                test=round(r[d > R.TRAIN_END].net.sum()), total=round(r.net.sum()), dd=round(dd),
                since_sep25=round(r[d >= "2025-09-01"].net.sum()), before_sep25=round(r[d < "2025-09-01"].net.sum()),
                years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                neg_years=int((r.groupby(r.entry_ts.dt.year).net.sum() < 0).sum()))


rows = []
for w in WEEK:
    for d in DAY:
        r = run(w, d, 6)
        rows.append(dict(week=w, day=d, **summ(r)))
g = pd.DataFrame(rows)
g["score"] = g.train / (1 + g.train.abs() * 0 + 1)  # placeholder, overwritten below
tr_dd = []
g.to_csv(R.OUT / "layers_grid.csv", index=False)
pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 52)
print(g.drop(columns=["years", "score"]).sort_values("train", ascending=False).to_string(index=False))
json.dump(rows, open(R.OUT / "layers.json", "w"), indent=1, default=str)
