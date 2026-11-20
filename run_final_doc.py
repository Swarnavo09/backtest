"""Numbers for the strategy PDF: Mon/Tue/Thu only, 30-min EMA filter, 15:00 exit, loss limit Rs 3,000/lot."""
import json
from datetime import time
import numpy as np, pandas as pd
import run_tune as U, run_v2 as R

U._init()
out = {}
for lots in (4, 6):
    r = U.simulate("none", time(9, 30), time(13, 30), {2, 4, 5, 6}, lots)   # only Mon, Tue, Thu
    r = r.sort_values("entry_ts").reset_index(drop=True)
    r["wd"] = r.entry_ts.dt.day_name()
    eq = r.net.cumsum(); dd = (eq - eq.cummax().clip(lower=0))
    m = r.groupby(r.entry_ts.dt.strftime("%Y-%m")).net.sum()
    loss_run = 0; best_run = 0
    for v in r.net:
        loss_run = loss_run + 1 if v <= 0 else 0; best_run = max(best_run, loss_run)
    w, l = r.net[r.net > 0], r.net[r.net <= 0]
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    out[lots] = dict(
        trades=len(r), win=round(100 * (r.net > 0).mean(), 1), total=round(r.net.sum()),
        pf=round(w.sum() / -l.sum(), 2), avg_win=round(w.mean()), avg_loss=round(l.mean()),
        best_trade=round(r.net.max()), worst_trade=round(r.net.min()),
        max_dd=round(dd.min()), max_loss_streak=best_run,
        best_month=[m.idxmax(), round(m.max())], worst_month=[m.idxmin(), round(m.min())],
        months_up=int((m > 0).sum()), months=int(len(m)),
        train=R.stats(r[d <= R.TRAIN_END])["net"], test=R.stats(r[d > R.TRAIN_END])["net"],
        years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
        trades_per_year={int(k): int(v) for k, v in r.groupby(r.entry_ts.dt.year).size().items()},
        by_day={k: dict(n=int(len(g)), net=round(g.net.sum()), avg=round(g.net.mean()), win=round(100 * (g.net > 0).mean(), 1)) for k, g in r.groupby("wd")},
        reasons=r.reason.value_counts().to_dict(),
        last12=round(m.iloc[-12:].sum()), last12_up=int((m.iloc[-12:] > 0).sum()),
        equity=[[str(t.date()), round(v)] for t, v in zip(r.entry_ts, eq)][::4] + [[str(r.entry_ts.iloc[-1].date()), round(eq.iloc[-1])]],
        monthly={k: round(v) for k, v in m.items()},
    )
    r.to_csv(R.OUT / f"final_mtt_trades_{lots}lots.csv", index=False)
json.dump(out, open(R.OUT / "final_mtt.json", "w"), indent=1, default=str)
for lots, v in out.items():
    print(lots, {k: v[k] for k in ("trades", "win", "total", "pf", "avg_win", "avg_loss", "best_trade", "worst_trade", "max_dd", "max_loss_streak", "best_month", "worst_month", "months_up", "months", "train", "test", "last12", "last12_up")})
    print("  years", v["years"], "| per year", v["trades_per_year"]); print("  by day", v["by_day"], "| reasons", v["reasons"])
