"""Index-friendly replacements for VWAP: moving averages on the 15-minute chart.
25 x 15-minute candles = one trading day, 125 = one week.

    python run_ma_proxy.py   -> results/ma_proxy.json
"""
import json
from dataclasses import replace
from multiprocessing import Pool

import numpy as np

import realiv
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest

VARIANTS = {
    "vwap (reference)": ("vwap", None),
    "SMA 25 (1 day)": ("none", [("sma", 25)]),
    "EMA 25 (1 day)": ("none", [("ema", 25)]),
    "EMA 50 (2 days)": ("none", [("ema", 50)]),
    "SMA 25 + SMA 125 (day + week)": ("none", [("sma", 25), ("sma", 125)]),
    "EMA 25 + EMA 125 (day + week)": ("none", [("ema", 25), ("ema", 125)]),
    "EMA 200": ("none", [("ema", 200)]),
}
_b = _v = None


def _init():
    global _b, _v
    _b, _v = R.load()


def run(args):
    name, trig, mt = args
    bias, mas = VARIANTS[name]
    df = add_signals_v2(_b, trig, bias, st=(10, 3.0))
    if mas:
        for kind, n in mas:
            ma = df.Close.rolling(n).mean() if kind == "sma" else df.Close.ewm(span=n, adjust=False).mean()
            df["bull"] &= (df.Close > ma).values
            df["bear"] &= (df.Close < ma).values
    tr = backtest(df, _v, replace(R.mk(**V.BASE), max_trades=mt))
    return dict(name=name, trigger=trig, max_trades=mt, **V.summ(tr))


def main():
    realiv.install("mix70v")
    jobs = [(n, t, 1) for n in VARIANTS for t in ("st_ema", "all3")]
    with Pool(4, initializer=_init) as p:
        res = p.map(run, jobs)
    (R.OUT / "ma_proxy.json").write_text(json.dumps(res, indent=1, default=str))
    for r in res:
        print(f"{r['name']:32} {r['trigger']:7} | n{r['all']['n']:5} all {r['all']['net']:>9} dd {r['all']['dd']:>9}"
              f" | train {r['train']['net']:>8} test {r['test']['net']:>8} pf {r['test']['pf']} | last12 {r['last12']:>7} | yrs {r['years']}")


if __name__ == "__main__":
    main()
