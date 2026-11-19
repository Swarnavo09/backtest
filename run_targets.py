"""Overall profit target (risk:reward) on the final strategy, 4 and 6 lots.

    python run_targets.py   -> results/targets.json
"""
import json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import run_ar_filters as AF
import run_exits as E
import run_trailing as T
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest

RATIOS = [None, 1.0, 1.5, 2.0, 2.5, 3.0]


def job(lots):
    T._init()
    df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
    f = AF.filt("30m EMA 9/21", df)
    df["bull"] &= f[0]; df["bear"] &= f[1]
    el, es = E.exit_arrays(df, "30m EMA 9/21 flips")
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, lots=lots)
    tr = backtest(df, AF._v, p)
    loss = 3000 * lots
    rows = []
    for sq in (time(15, 0), time(15, 10)):
        for rr in RATIOS:
            r = E.simulate(df, tr, replace(p, squareoff=sq), el, es, loss, None if rr is None else rr * loss)
            d = r.entry_ts.dt.strftime("%Y-%m-%d")
            rows.append(dict(lots=lots, squareoff=sq.strftime("%H:%M"), rr=rr, target=None if rr is None else rr * loss,
                             train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                             hit_pct=round(100 * (r.reason == "target").mean(), 1),
                             years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()}))
    return rows


def main():
    with Pool(2) as pool:
        res = [x for c in pool.map(job, [4, 6]) for x in c]
    (R.OUT / "targets.json").write_text(json.dumps(res, indent=1, default=str))
    for r in res:
        print(f"{r['lots']} lots {r['squareoff']} RR {str(r['rr']):4} target {str(r['target']):7} | hit {r['hit_pct']:5}% | all {r['all']['net']:>9} "
              f"dd {r['all']['dd']:>9} pf {r['all']['pf']} win {r['all']['win']} | train {r['train']['net']:>8} test {r['test']['net']:>8} | {r['years']}")


if __name__ == "__main__":
    main()
