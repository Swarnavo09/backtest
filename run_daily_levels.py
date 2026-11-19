"""Daily-anchored levels that work on an index (no volume needed), as VWAP replacements.

    python run_daily_levels.py   -> results/daily_levels.json
"""
import json
from dataclasses import replace
from multiprocessing import Pool

import numpy as np
import pandas as pd

import realiv
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest

_b = _v = None


def _init():
    global _b, _v
    _b, _v = R.load()


def levels(df):
    day = pd.Series(df.index.date, index=df.index)
    d = df.groupby(day).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    prev = d.shift(1)
    P = (prev.h + prev.l + prev.c) / 3
    BC = (prev.h + prev.l) / 2
    TC = 2 * P - BC
    m = lambda s: day.map(s).values
    first = df.groupby(day).head(1)          # first 15-minute candle of each day
    fc = pd.Series(first.Close.values, index=first.index.date)
    fh = pd.Series(first.High.values, index=first.index.date)
    fl = pd.Series(first.Low.values, index=first.index.date)
    return dict(P=m(P), TC=m(np.maximum(TC, BC)), BC=m(np.minimum(TC, BC)), PC=m(prev.c),
                DO=m(d.o), FC=m(fc), FH=m(fh), FL=m(fl))


VARIANTS = {
    "VWAP (reference, needs volume)": None,
    "Daily Pivot P": lambda c, L: (c > L["P"], c < L["P"]),
    "CPR (above TC / below BC)": lambda c, L: (c > L["TC"], c < L["BC"]),
    "Previous day close": lambda c, L: (c > L["PC"], c < L["PC"]),
    "Today's open (first candle open)": lambda c, L: (c > L["DO"], c < L["DO"]),
    "First 15-min candle close": lambda c, L: (c > L["FC"], c < L["FC"]),
    "First 15-min candle high / low (breakout)": lambda c, L: (c > L["FH"], c < L["FL"]),
    "Pivot P + today's open": lambda c, L: ((c > L["P"]) & (c > L["DO"]), (c < L["P"]) & (c < L["DO"])),
}


def run(args):
    name, trig = args
    if VARIANTS[name] is None:
        df = add_signals_v2(_b, trig, "vwap", st=(10, 3.0))
    else:
        df = add_signals_v2(_b, trig, "none", st=(10, 3.0))
        L = levels(df)
        bu, be = VARIANTS[name](df.Close.values, L)
        df["bull"] &= bu
        df["bear"] &= be
    tr = backtest(df, _v, replace(R.mk(**V.BASE), max_trades=1))
    return dict(name=name, trigger=trig, **V.summ(tr))


def main():
    realiv.install("mix70v")
    with Pool(4, initializer=_init) as p:
        res = p.map(run, [(n, t) for n in VARIANTS for t in ("st_ema", "all3")])
    (R.OUT / "daily_levels.json").write_text(json.dumps(res, indent=1, default=str))
    for r in res:
        print(f"{r['name']:42} {r['trigger']:7} | n{r['all']['n']:5} all {r['all']['net']:>9} dd {r['all']['dd']:>9}"
              f" | train {r['train']['net']:>8} test {r['test']['net']:>8} pf {r['test']['pf']} | last12 {r['last12']:>7} | yrs {r['years']}")


if __name__ == "__main__":
    main()
