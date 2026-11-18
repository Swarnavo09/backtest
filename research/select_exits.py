"""Choose SL / target / trail on DEVELOPMENT data only (2019-03 .. 2024-11-17).
Entry = good-setup Supertrend flip, next-week expiry, 4 lots, max 2 trades/day."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import itertools, pandas as pd
from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat
DEV = ("2019-03-01", "2024-11-17")
GOOD = dict(htf_minutes=60, adx_min=25, window=("09:25", "11:00"))
def cfg_for(sl, plan, lock, stx, daily_cap=None):
    c = dict(stop="rupee", partial_at=None, max_trades=2, lots=4, expiry="next", st_exit=stx, **GOOD,
             sl_total=sl, lock_trigger=sl, trail_frac=0.5, trail_mode="incremental", runner_trail=0.6,
             lock_level=500 if lock == "lock 500" else sl * 0.5, daily_cap=daily_cap or 2 * sl + 1000)
    if plan == "2R full": c.update(partial_total=None, final_total=2 * sl)
    elif plan == "3R full": c.update(partial_total=None, final_total=3 * sl)
    else: c.update(partial_total=2 * sl, final_total=3 * sl)
    return c
if __name__ == "__main__":
    df = C.load_1m(); df = df[df.index >= "2018-09-01"]; lab = Lab(df); rows = []
    for m, sl, plan, lock, stx in itertools.product((10, 15), (3000, 4000, 5000, 6000), ("2R full", "3R full", "2R book 3 lots + 3R runner"),
                                                    ("lock 500", "lock 0.5R"), (False, True)):
        t = lab.run(m, *DEV, **cfg_for(sl, plan, lock, stx)); s = stat(t)
        t["y"] = pd.to_datetime(t.date).dt.year
        yrs = t.groupby("y").net_pnl.sum()
        rows.append(dict(tf=m, SL=sl, plan=plan, lock=lock, st_exit=stx, n=s["n"], win=round(s["win"], 1), pf=round(s["pf"], 2),
                         net_per_yr=round(s["per_yr"]), pos_years=f"{(yrs > 0).sum()}/{len(yrs)}"))
    r = pd.DataFrame(rows).sort_values("pf", ascending=False)
    r.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "select_exits_dev.csv"), index=False)
    pd.set_option("display.width", 200); print(r.head(15).to_string(index=False)); print("...\nprofitable on dev:", (r.pf > 1).sum(), "/", len(r))
    print(r.groupby("SL").pf.mean().round(3).to_dict(), r.groupby("plan").pf.mean().round(3).to_dict(), r.groupby("lock").pf.mean().round(3).to_dict(), r.groupby("st_exit").pf.mean().round(3).to_dict(), r.groupby("tf").pf.mean().round(3).to_dict())
