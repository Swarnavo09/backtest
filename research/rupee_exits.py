"""User's rupee-based exit plan, 4 lots, last 2 years:
SL Rs 2,500 | at +1,500 stop -> +300 | then trail 60% | at +6,000 book 3 lots, 1-lot runner to +8,000 total.
Max 2 trades/day, Rs 10k daily cap, optional 'good setup' skip filter. Prior years re-run for robustness."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import itertools, pandas as pd
from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat
LAST2Y, PRIOR = ("2024-11-18", "2026-11-18"), ("2019-03-01", "2024-11-17")
GOOD = dict(htf_minutes=60, adx_min=25, window=("09:25", "11:00"))
BASE = dict(stop="rupee", partial_at=None, daily_cap=10_000, max_trades=2, lots=4)
df = C.load_1m(); df = df[df.index >= "2018-09-01"]; lab = Lab(df)
rows, keep = [], {}
for m, filt, stx, tmode in itertools.product((5, 10, 15), ("all signals", "good setups only"), (False, True), ("incremental", "of_peak")):
    cfg = dict(BASE, st_exit=stx, trail_mode=tmode, **(GOOD if filt != "all signals" else {}))
    t = lab.run(m, *LAST2Y, **cfg); s = stat(t); p = stat(lab.run(m, *PRIOR, **cfg))
    eq = t.groupby("date").net_pnl.sum().cumsum() if len(t) else pd.Series([0])
    t["yr"] = (pd.to_datetime(t.date) >= "2025-11-18").map({False: "y1", True: "y2"})
    rows.append(dict(tf=f"{m}m", filter=filt, st_exit=stx, trail=tmode, trades=s["n"], win=round(s["win"], 1), pf=round(s["pf"], 2),
                     net_2y=round(s["net"]), yr1=round(t[t.yr == "y1"].net_pnl.sum()), yr2=round(t[t.yr == "y2"].net_pnl.sum()),
                     max_dd=round((eq - eq.cummax()).min()), prior_pf=round(p["pf"], 2), prior_per_yr=round(p["per_yr"])))
    keep[(m, filt, stx, tmode)] = t
r = pd.DataFrame(rows).sort_values("net_2y", ascending=False)
pd.set_option("display.width", 230)
print(r.to_string(index=False))
r.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rupee_exits_grid.csv"), index=False)
best = r.iloc[0]; k = (int(best.tf[:-1]), best["filter"], best.st_exit, best.trail)
bt_ = keep[k].drop(columns=["yr"]); bt_.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rupee_exits_best_trades.csv"), index=False)
main = keep[(10, "good setups only", False, "incremental")].drop(columns=["yr"])
main.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rupee_exits_10m_good_trades.csv"), index=False)
for nm, t in (("BEST", bt_), ("10m good/no-ST/incremental", main)):
    print(f"\n== {nm}: exit reasons"); print(t.groupby("exit_reason").net_pnl.agg(["count", "mean", "sum"]).round(0).sort_values("count", ascending=False).to_string())
    print(t.groupby("direction").net_pnl.agg(["count", "sum", lambda x: round((x > 0).mean() * 100, 1)]).to_string())
