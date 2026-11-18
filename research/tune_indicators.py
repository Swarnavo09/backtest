"""Stage 1: tune Supertrend (period, multiplier) and ADX (period, threshold) with the final exits fixed.
Selection on DEV (2019-03 .. 2024-11-17) only; TEST (last 2 years) is recorded but NOT used to choose.
usage: python research/tune_indicators.py <tf> <st_period> [...]"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import itertools, pandas as pd
import run_final as R
from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat
def evaluate(lab, tf, cfg):
    dev, test = lab.run(tf, *R.DEV, **cfg), lab.run(tf, R.START, R.END, **cfg)
    a, b = stat(dev), stat(test)
    yrs = dev.assign(y=pd.to_datetime(dev.date).dt.year).groupby("y").net_pnl.sum() if len(dev) else pd.Series(dtype=float)
    return dict(dev_n=a["n"], dev_win=round(a["win"], 1), dev_pf=round(a["pf"], 2), dev_per_yr=round(a.get("per_yr", 0)),
                dev_pos_years=int((yrs > 0).sum()), test_n=b["n"], test_win=round(b["win"], 1), test_pf=round(b["pf"], 2),
                test_net=round(b["net"]))
if __name__ == "__main__":
    tf = int(sys.argv[1]); periods = [int(x) for x in sys.argv[2:]]
    df = C.load_1m(); df = df[df.index >= "2018-09-01"]; lab = Lab(df); rows = []
    for p, mlt, an, amin in itertools.product(periods, (2.0, 2.5, 3.0, 4.0), (10, 14, 20), (20, 25, 30)):
        cfg = dict(R.FINAL, st_period=p, st_mult=mlt, adx_period=an, adx_min=amin)
        rows.append(dict(tf=tf, st_period=p, st_mult=mlt, adx_period=an, adx_min=amin, **evaluate(lab, tf, cfg)))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tune_ind_{tf}_{'_'.join(map(str, periods))}.csv"), index=False)
