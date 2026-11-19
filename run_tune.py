"""Fine-tune the intraday spread strategy with AlgoRooms-buildable filters / day skips.

Base: Supertrend(10,3)+EMA 9/21 trigger on 15m, 30-min EMA 9/21 filter, sell ATM / buy OTM 300,
exit when 30-min EMA flips or 15:00, loss limit Rs 3,000 per lot, max 1 trade/day.

    python run_tune.py   -> results/tune.json
"""
import bisect, itertools, json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import run_ar_filters as AF
import run_exits as E
import run_trailing as T
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest, ema, supertrend

_G = {}


def _init():
    T._init()
    df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
    f = AF.filt("30m EMA 9/21", df)
    df["bull"] &= f[0]; df["bear"] &= f[1]
    _G["base"] = df
    _G["el"], _G["es"] = E.exit_arrays(df, "30m EMA 9/21 flips")
    # 1-hour proxies for daily / weekly trend (known only from COMPLETED 1H candles)
    b5 = AF._b5
    h = b5.resample("60min", offset="15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    close_ts = [min(t + pd.Timedelta(minutes=60), t.normalize() + pd.Timedelta(hours=15, minutes=30)) for t in h.index]
    sig_close = df.index + pd.Timedelta(minutes=15)

    def onbars(series):
        s = pd.Series(np.asarray(series, float), index=pd.DatetimeIndex(close_ts))
        s = s[~s.index.duplicated(keep="last")]
        return s.reindex(s.index.union(sig_close)).ffill().reindex(sig_close).values

    hc = h.Close
    _G["h"] = {
        "c_ema140": onbars(np.sign(hc - ema(hc, 140))),
        "c_ema350": onbars(np.sign(hc - ema(hc, 350))),
        "ema140_350": onbars(np.sign(ema(hc, 140) - ema(hc, 350))),
        "ema50_200": onbars(np.sign(ema(hc, 50) - ema(hc, 200))),
        "st_1h": onbars(supertrend(h, 10, 3.0)[0]),
    }
    a, p, n = AF.adx(df)
    _G["adx"], _G["pdi"], _G["ndi"] = a.values, p.values, n.values
    _G["rsi"] = AF.rsi(df.Close).values
    import realiv
    rv = realiv.install("mix70v")
    _G["expday"] = np.array([rv.expiries[bisect.bisect_left(rv.expiries, d)] == d for d in df.index.date])


def masks(name):
    df, H = _G["base"], _G["h"]
    n = len(df); one = np.ones(n, bool)
    if name == "none": return one, one
    if name == "1H close vs EMA140 (daily trend)": return H["c_ema140"] > 0, H["c_ema140"] < 0
    if name == "1H close vs EMA350 (weekly trend)": return H["c_ema350"] > 0, H["c_ema350"] < 0
    if name == "1H EMA140 vs EMA350 (daily+weekly)": return H["ema140_350"] > 0, H["ema140_350"] < 0
    if name == "1H close>EMA140 & EMA140>EMA350": return (H["c_ema140"] > 0) & (H["ema140_350"] > 0), (H["c_ema140"] < 0) & (H["ema140_350"] < 0)
    if name == "1H EMA50 vs EMA200": return H["ema50_200"] > 0, H["ema50_200"] < 0
    if name == "1H Supertrend": return H["st_1h"] > 0, H["st_1h"] < 0
    if name == "ADX > 20": return (_G["adx"] > 20) & (_G["pdi"] > _G["ndi"]), (_G["adx"] > 20) & (_G["ndi"] > _G["pdi"])
    if name == "RSI not stretched (40-70 / 30-60)": r = _G["rsi"]; return (r > 40) & (r < 70), (r > 30) & (r < 60)
    if name == "RSI momentum (>55 / <45)": r = _G["rsi"]; return r > 55, r < 45
    raise ValueError(name)


FILTERS = ["none", "1H close vs EMA140 (daily trend)", "1H close vs EMA350 (weekly trend)", "1H EMA140 vs EMA350 (daily+weekly)",
           "1H close>EMA140 & EMA140>EMA350", "1H EMA50 vs EMA200", "1H Supertrend", "ADX > 20",
           "RSI not stretched (40-70 / 30-60)", "RSI momentum (>55 / <45)"]
STARTS = [time(9, 30), time(9, 45), time(10, 0), time(10, 30)]
LASTS = [time(13, 30), time(12, 30), time(11, 30)]
DAYS = {"all days": None, "skip Friday": {4}, "skip Monday": {0}, "skip Mon+Fri": {0, 4}}


def simulate(filt, start, last, skip, lots, sq=time(15, 0)):
    df = _G["base"].copy()
    bu, be = masks(filt)
    if skip:
        ok = ~np.isin(df.index.weekday, list(skip))
        bu = bu & ok; be = be & ok
    df["bull"] &= bu; df["bear"] &= be
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, lots=lots, start=start, last_entry=last)
    tr = backtest(df, AF._v, p)
    r = E.simulate(df, tr, replace(p, squareoff=sq), _G["el"], _G["es"], 3000 * lots)
    return r


def summ(r):
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    m = r.groupby(r.entry_ts.dt.strftime("%Y-%m")).net.sum()
    return dict(train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                months_up=int((m > 0).sum()), months=int(len(m)), last12=round(m.iloc[-12:].sum()),
                days=int(r.entry_ts.dt.date.nunique()))


def job(args):
    filt, start, last, dname = args
    r = simulate(filt, start, last, DAYS[dname], 6)
    return dict(filter=filt, start=start.strftime("%H:%M"), last=last.strftime("%H:%M"), days_rule=dname, **summ(r))


def main():
    with Pool(4, initializer=_init) as pool:
        # 0) weekday / expiry breakdown of the current strategy
        base = pool.apply(_breakdown)
        print("Current strategy, 6 lots, by weekday / day type:"); print(base)
        grid = list(itertools.product(FILTERS, STARTS, LASTS, DAYS))
        res = pool.map(job, grid, chunksize=4)
    g = pd.DataFrame([dict(filter=r["filter"], start=r["start"], last=r["last"], days_rule=r["days_rule"],
                           train=r["train"]["net"], tr_dd=r["train"]["dd"], test=r["test"]["net"], te_dd=r["test"]["dd"],
                           all=r["all"]["net"], dd=r["all"]["dd"], pf=r["all"]["pf"], trades=r["all"]["n"],
                           neg=sum(v < 0 for v in r["years"].values()), last12=r["last12"]) for r in res])
    g.to_csv(R.OUT / "tune_grid.csv", index=False)
    (R.OUT / "tune.json").write_text(json.dumps(res, indent=1, default=str))
    cur = g[(g["filter"] == "none") & (g.start == "09:30") & (g["last"] == "13:30") & (g.days_rule == "all days")].iloc[0]
    print("\nCURRENT:", cur.to_dict())
    g["score"] = g.train / (1 + g.tr_dd.abs() / 50000)          # train-only: profit adjusted for drawdown
    print("\nTop 15 by 2022-24 score:")
    print(g.sort_values("score", ascending=False).head(15).drop(columns="score").to_string(index=False))
    print("\nEach filter alone (09:30-13:30, all days):")
    print(g[(g.start == "09:30") & (g["last"] == "13:30") & (g.days_rule == "all days")].drop(columns="score").to_string(index=False))


def _breakdown():
    r = simulate("none", time(9, 30), time(13, 30), None, 6)
    r["wd"] = r.entry_ts.dt.day_name()
    idx = {t: i for i, t in enumerate(_G["base"].index)}
    r["expday"] = [_G["expday"][idx[t]] for t in r.entry_ts]
    a = r.groupby("wd").net.agg(["size", "sum", "mean"]).round()
    b = r.groupby("expday").net.agg(["size", "sum", "mean"]).round()
    r["hour"] = r.entry_ts.dt.strftime("%H")
    c = r.groupby("hour").net.agg(["size", "sum", "mean"]).round()
    return pd.concat({"weekday": a, "expiry day": b, "entry hour": c}).to_string()


if __name__ == "__main__":
    main()
