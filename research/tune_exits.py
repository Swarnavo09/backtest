"""Stage 2: choose SL / reward:risk for the robust indicator cluster (15-min, ADX(14) > 30).
Each exit setting is scored by its AVERAGE dev result across the 7 cluster members (robust choice)."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import itertools, pandas as pd
import run_final as R
from bt import common as C
from bt.cs_lab import Lab
from research.tune_indicators import evaluate
CLUSTER = [(10, 2.0), (7, 2.0), (7, 2.5), (14, 2.5), (20, 2.0), (14, 2.0), (10, 2.5)]
if __name__ == "__main__":
    sls = [int(x) for x in sys.argv[1:]]
    df = C.load_1m(); df = df[df.index >= "2018-09-01"]; lab = Lab(df); rows = []
    for sl, rr, (p, m) in itertools.product(sls, (2, 3), CLUSTER):
        cfg = dict(R.FINAL, st_period=p, st_mult=m, adx_period=14, adx_min=30, sl_total=sl, final_total=rr * sl,
                   lock_trigger=sl, lock_level=500, daily_cap=max(10_000, 2 * sl))
        rows.append(dict(SL=sl, RR=f"1:{rr}", st_period=p, st_mult=m, **evaluate(lab, 15, cfg))); print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tune_exits_{'_'.join(map(str, sls))}.csv"), index=False)
