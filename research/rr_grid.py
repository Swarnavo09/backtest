"""Wider stop + fixed reward:risk (1:2 / 1:3), Rs 10,000 daily cap, max 2 trades/day, optional
'good setup' day filter. Main period = last 1 year; same configs re-run on 2019-03..2025-11 to
check the result is not luck."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import itertools, pandas as pd
from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat
LAST1Y, PRIOR = ("2025-11-18", "2026-11-18"), ("2019-03-01", "2025-11-17")
GOOD = dict(htf_minutes=60, adx_min=25, window=("09:25", "11:00"))   # 'skip the day unless setup is good'
df = C.load_1m(); df = df[df.index >= "2018-09-01"]; lab = Lab(df)
rows = []
for m, sl, rr, filt, stx in itertools.product((5, 10, 15), (1.5, 2, 3, 4, 5), (2, 3), ("all signals", "good setups only"), (True, False)):
    cfg = dict(stop="fixed", init_stop=-sl, target_pct=sl * rr, partial_at=None, daily_cap=10_000, max_trades=2, st_exit=stx)
    if filt != "all signals": cfg.update(GOOD)
    t = lab.run(m, *LAST1Y, **cfg); s = stat(t)
    tg = (t.exit_reason.str.startswith("target").mean() * 100) if len(t) else 0
    rows.append(dict(tf=f"{m}m", SL=f"-{sl}%", RR=f"1:{rr}", filter=filt, st_exit=stx, trades=s["n"], win=round(s["win"], 1),
                     target_hit_pct=round(tg), pf=round(s["pf"], 2), net_1y=round(s["net"]),
                     max_dd=round((t.groupby("date").net_pnl.sum().cumsum().pipe(lambda e: e - e.cummax())).min()) if len(t) else 0))
r = pd.DataFrame(rows).sort_values("net_1y", ascending=False)
r.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rr_grid_last1y.csv"), index=False)
pd.set_option("display.width", 220)
print("== TOP 12 of", len(r), "configs, last 1 year"); print(r.head(12).to_string(index=False))
print("\n== how many configs were profitable:", (r.net_1y > 0).sum(), "of", len(r))
print("\n== BOTTOM 5"); print(r.tail(5).to_string(index=False))
# robustness of top 6 on prior years
print("\n== top 6 re-run on 2019-03 .. 2025-11 (never used for selection)")
for _, x in r.head(6).iterrows():
    sl, rr = float(x.SL.strip("-%")), int(x.RR[-1]); m = int(x.tf[:-1])
    cfg = dict(stop="fixed", init_stop=-sl, target_pct=sl * rr, partial_at=None, daily_cap=10_000, max_trades=2, st_exit=x.st_exit)
    if x["filter"] != "all signals": cfg.update(GOOD)
    t = lab.run(m, *PRIOR, **cfg); s = stat(t)
    print(f"{x.tf} SL{x.SL} {x.RR} {x['filter']:17s} st_exit={x.st_exit!s:5s} | last1y net ₹{x.net_1y:>8,} PF {x.pf} | prior: n={s['n']} PF={s['pf']:.2f} net/yr=₹{s['per_yr']:,.0f}")
