"""Sold strike / hedge comparison with the final rules: 30-min EMA filter, exit when the
30-min EMA flips, square-off 15:00 (also 14:45, 15:10), loss limit Rs 3,000 per lot.

    python run_strikes.py   -> results/strikes.json
"""
import json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import pandas as pd

import run_ar_filters as AF
import run_exits as E
import run_trailing as T
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest

# (label, short_offset, hedge distance from the SOLD strike)
STRIKES = [("Sell ATM · buy OTM 300", 0, 300),
           ("Sell OTM 100 · buy OTM 300", -100, 200),
           ("Sell OTM 100 · buy OTM 400", -100, 300),
           ("Sell ITM 100 · buy OTM 200", 100, 300)]


def job(args):
    label, off, hedge = args
    T._init()
    df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
    f = AF.filt("30m EMA 9/21", df)
    df["bull"] &= f[0]; df["bear"] &= f[1]
    el, es = E.exit_arrays(df, "30m EMA 9/21 flips")
    rows = []
    for lots in (4, 6):
        p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, short_offset=off, hedge=hedge, lots=lots)
        tr = backtest(df, AF._v, p)
        for sq in (time(14, 45), time(15, 0), time(15, 10)):
            r = E.simulate(df, tr, replace(p, squareoff=sq), el, es, 3000 * lots)
            d = r.entry_ts.dt.strftime("%Y-%m-%d")
            m = r.groupby(r.entry_ts.dt.strftime("%Y-%m")).net.sum()
            rows.append(dict(strikes=label, lots=lots, squareoff=sq.strftime("%H:%M"),
                             train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                             years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                             months_up=int((m > 0).sum()), months=int(len(m)), last12=round(m.iloc[-12:].sum()),
                             avg_credit=round(tr.credit.mean(), 1), avg_sl=round(r[r.reason == "sl"].net.mean())))
    return rows


def main():
    with Pool(4) as pool:
        res = [x for c in pool.map(job, STRIKES) for x in c]
    (R.OUT / "strikes.json").write_text(json.dumps(res, indent=1, default=str))
    for lots in (4, 6):
        print(f"\n=== {lots} lots")
        for r in sorted([r for r in res if r["lots"] == lots], key=lambda r: -r["all"]["net"]):
            print(f"{r['strikes']:28} {r['squareoff']} | all {r['all']['net']:>9} dd {r['all']['dd']:>9} pf {r['all']['pf']} win {r['all']['win']}"
                  f" | train {r['train']['net']:>8} test {r['test']['net']:>8} | last12 {r['last12']:>8} | months up {r['months_up']}/{r['months']}"
                  f" | credit {r['avg_credit']} avgSL {r['avg_sl']} | {r['years']}")


if __name__ == "__main__":
    main()
