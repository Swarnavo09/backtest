"""One-change-at-a-time refinement test of the Supertrend credit spread.
DEV  = 2019-03-01 .. 2023-11-17 (rules are judged here)
TEST = 2023-11-18 .. 2026-11-18 (the user's 3 years - only looked at after choosing)"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from bt import common as C
from bt.cs_lab import Lab
DEV, TEST = ("2019-03-01", "2023-11-17"), ("2023-11-18", "2026-11-18")
VARIANTS = {
    "base (your rules)": {},
    "E: flip candle only": dict(flip_candle_only=True),
    "E: ADX > 25": dict(adx_min=25),
    "E: window 09:25-11:00": dict(window=("09:25", "11:00")),
    "E: with day's move >=0.15 ATR": dict(trend_filter_atr=0.15),
    "E: with day's move >=0.30 ATR": dict(trend_filter_atr=0.30),
    "E: 1-hour Supertrend agrees": dict(htf_minutes=60),
    "D: FADE the flip": dict(direction="fade"),
    "X: no % stop (ST close/cap/15:15)": dict(stop="none"),
    "X: initial stop -1.0%": dict(init_stop=-1.0),
    "X: initial stop -2.5%": dict(init_stop=-2.5),
    "X: no partial booking": dict(partial_at=None),
    "X: no Supertrend exit": dict(st_exit=False),
    "S: nearest expiry (0-4 DTE)": dict(expiry="nearest"),
    "S: short strike 200 pts OTM": dict(short_offset=200),
    "M: theta in market hours only": dict(time_model="trading"),
}
def stat(t):
    if len(t) == 0: return dict(n=0, net=0, win=0, pf=0)
    w, l = t.net_pnl[t.net_pnl > 0].sum(), -t.net_pnl[t.net_pnl <= 0].sum()
    yrs = (pd.to_datetime(t.date).max() - pd.to_datetime(t.date).min()).days / 365.25
    return dict(n=len(t), net=t.net_pnl.sum(), per_yr=t.net_pnl.sum() / max(yrs, .5), win=(t.net_pnl > 0).mean() * 100, pf=w / max(l, 1))
if __name__ == "__main__":
    tfs = [int(x) for x in sys.argv[1:]] or [5, 10, 15]
    df = C.load_1m(); df = df[df.index >= "2018-09-01"]
    lab = Lab(df); rows = []
    for m in tfs:
        for name, cfg in VARIANTS.items():
            a, b = stat(lab.run(m, *DEV, **cfg)), stat(lab.run(m, *TEST, **cfg))
            rows.append(dict(tf=f"{m}m", variant=name, dev_n=a["n"], dev_win=round(a["win"], 1), dev_pf=round(a["pf"], 2),
                             dev_per_yr=round(a.get("per_yr", 0)), test_n=b["n"], test_win=round(b["win"], 1),
                             test_pf=round(b["pf"], 2), test_net=round(b["net"])))
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"grid_{'_'.join(map(str,tfs))}.csv"), index=False)
