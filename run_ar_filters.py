"""Day filters that can be built in AlgoRooms (no daily/weekly candles, no VWAP, no first candle).

    python run_ar_filters.py   -> results/ar_filters.json
"""
import json
from dataclasses import replace
from multiprocessing import Pool

import numpy as np
import pandas as pd

import realiv
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest, ema, supertrend, macd

_b = _v = _b5 = None


def _init():
    global _b, _v, _b5
    _b, _v = R.load()
    from strategy import load_bars
    b5 = load_bars(R.DATA / "nifty_5m_5y.csv", 5)
    _b5 = b5[np.isin(b5.index.date, list(set(_b.index.date)))]


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def adx(df, n=14):
    h, l, c = df.High, df.Low, df.Close
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, ndi


def htf(minutes, kind):
    """Higher-timeframe direction (+1/-1), known only once that candle has CLOSED."""
    h = (_b5.resample(f"{minutes}min", offset="15min")
         .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna())
    if kind == "st":
        d, _ = supertrend(h, 10, 3.0)
    elif kind == "ema":
        d = np.sign(ema(h.Close, 9) - ema(h.Close, 21))
    elif kind == "macd":
        m, s = macd(h.Close)
        d = np.sign(m - s)
    close_ts = [min(t + pd.Timedelta(minutes=minutes), t.normalize() + pd.Timedelta(hours=15, minutes=30)) for t in h.index]
    s = pd.Series(np.asarray(d, dtype=float), index=pd.DatetimeIndex(close_ts))
    s = s[~s.index.duplicated(keep="last")]
    sig_close = _b.index + pd.Timedelta(minutes=15)
    return s.reindex(s.index.union(sig_close)).ffill().reindex(sig_close).values


def filt(name, df):
    c = df.Close
    if name in ("none", "VWAP (reference)"):
        return None
    if name == "green/red signal candle":
        return (c > df.Open).values, (c < df.Open).values
    if name.startswith("RSI"):
        lo, hi = {"RSI 55/45": (55, 45), "RSI 60/40": (60, 40)}[name]
        r = rsi(c)
        return (r > lo).values, (r < hi).values
    if name.startswith("ADX"):
        th = int(name.split()[1])
        a, p, n = adx(df)
        return ((a > th) & (p > n)).values, ((a > th) & (n > p)).values
    if name.startswith("EMA 50 > 200") or name == "EMA 50/200 trend":
        e50, e200 = ema(c, 50), ema(c, 200)
        return ((e50 > e200) & (c > e50)).values, ((e50 < e200) & (c < e50)).values
    if name == "MACD above/below 0":
        m, s = macd(c)
        return (m > 0).values, (m < 0).values
    if name.startswith("1H") or name.startswith("30m"):
        mins = 60 if name.startswith("1H") else 30
        kinds = name.split(" ", 1)[1].split(" + ")
        bu = np.ones(len(df), bool); be = np.ones(len(df), bool)
        for k in kinds:
            d = htf(mins, {"Supertrend": "st", "EMA 9/21": "ema", "MACD": "macd"}[k])
            bu &= d > 0; be &= d < 0
        return bu, be
    raise ValueError(name)


FILTERS = ["none", "green/red signal candle", "RSI 55/45", "RSI 60/40", "ADX 20", "ADX 25",
           "EMA 50/200 trend", "MACD above/below 0",
           "1H Supertrend", "1H EMA 9/21", "1H MACD", "1H Supertrend + EMA 9/21",
           "30m Supertrend", "30m EMA 9/21",
           "RSI 55/45 + 1H Supertrend", "ADX 20 + 1H Supertrend"]


def run(args):
    name, trig, fresh = args
    df = add_signals_v2(_b, trig, "vwap" if name == "VWAP (reference)" else "none", st=(10, 3.0))
    for part in name.split(" + 1H "):
        nm = part if part.startswith(("1H", "30m")) or part == name else part
        if " + 1H " in name and part != name.split(" + 1H ")[0]:
            nm = "1H " + part
        f = filt(nm, df)
        if f is not None:
            df["bull"] &= f[0]
            df["bear"] &= f[1]
    tr = backtest(df, _v, replace(R.mk(**V.BASE), max_trades=1, fresh=fresh))
    out = V.summ(tr)
    out["days_traded_pct"] = round(100 * tr.entry_ts.dt.date.nunique() / len(set(_b.index.date)), 1)
    return dict(name=name, trigger=trig, fresh=fresh, **out)


def main():
    realiv.install("mix70v")
    with Pool(4, initializer=_init) as p:
        res = p.map(run, [(f, t, False) for f in ["VWAP (reference)"] + FILTERS for t in ("st_ema", "all3")])
    (R.OUT / "ar_filters_level.json").write_text(json.dumps(res, indent=1, default=str))
    for r in sorted(res, key=lambda r: -r["train"]["net"]):
        y = r["years"]
        print(f"{r['name']:28} {r['trigger']:7} | days {r['days_traded_pct']:5}% | train {r['train']['net']:>8} test {r['test']['net']:>8} "
              f"pf {r['test']['pf']} | all {r['all']['net']:>9} dd {r['all']['dd']:>9} | neg yrs {sum(v < 0 for v in y.values())} | {y}")


if __name__ == "__main__":
    main()
