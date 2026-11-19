"""Build the v3 strategy report (report/index.html) from results/v3_*.

    python run_v3.py mix70v && python select_v3.py mix70v && python build_report_v3.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import run_v2 as R
from build_report import clean

ROOT = Path(__file__).parent
RES, REP = ROOT / "results", ROOT / "report"
CONV = sys.argv[1] if len(sys.argv) > 1 else "mix70v"


def main():
    sel = json.loads((RES / f"v3_selected_{CONV}.json").read_text())
    tr = pd.read_csv(RES / f"v3_trades_best_{CONV}.csv", parse_dates=["entry_ts", "exit_ts"])
    g = pd.read_csv(RES / f"v3_grid_{CONV}.csv")
    bars, vix = R.load()
    days = sorted(set(bars.index.date))

    # daily equity
    pnl = tr.groupby(tr.entry_ts.dt.date).net.sum()
    eq, run = [], 0.0
    for d in days:
        run += float(pnl.get(d, 0.0))
        eq.append({"label": d.strftime("%b %y"), "y": round(run)})
    # trade list sample (last 25)
    last = tr.tail(25)[["entry_ts", "exit_ts", "side", "short_strike", "hedge_strike", "spot_in", "spot_out",
                        "credit", "close_cost", "net", "reason"]].copy()
    last["entry_ts"] = last.entry_ts.dt.strftime("%d %b %Y %H:%M")
    last["exit_ts"] = last.exit_ts.dt.strftime("%H:%M")
    # factor medians across the whole grid (what generally helps)
    fac = {k: g.groupby(k).apply(lambda x: {"tr": float(x.tr_net.median()), "te": float(x.te_net.median())},
                                 include_groups=False).to_dict()
           for k in ("bias", "sigset", "exit_mode", "short_offset", "dte0", "start", "sl", "hedge")}
    # expiry-day split
    import realiv
    rv = realiv.install(CONV)
    import bisect
    tr["expday"] = [rv.expiries[bisect.bisect_left(rv.expiries, d)] == d for d in tr.entry_ts.dt.date]
    split = {("expiry" if k else "other"): dict(n=int(len(t)), net=round(t.net.sum()), avg=round(t.net.mean()))
             for k, t in tr.groupby("expday")}
    sides = {k: dict(n=int(len(t)), net=round(t.net.sum()), win=round(100 * (t.net > 0).mean(), 1))
             for k, t in tr.groupby("side")}

    data = dict(sel=sel, equity=eq, last=last.to_dict("records"), factors=fac, split=split, sides=sides,
                combos=len(g), pct_train=round(100 * (g.tr_net > 0).mean(), 1),
                pct_test=round(100 * (g.te_net > 0).mean(), 1),
                pct_both=round(100 * ((g.tr_net > 0) & (g.te_net > 0)).mean(), 1),
                first=str(days[0]), last_day=str(days[-1]), sessions=len(days), conv=CONV,
                last_close=round(float(bars.Close.iloc[-1]), 2),
                history=dict(
                    s59=json.loads((RES / "summary.json").read_text())["stage2"]["10"]["best"] if (RES / "summary.json").exists() else None,
                    year=json.loads((RES / "year_summary.json").read_text()) if (RES / "year_summary.json").exists() else None,
                    v2=dict(combos=int(len(pd.read_csv(RES / "v2_grid.csv")))) if (RES / "v2_grid.csv").exists() else None))
    if data["history"]["year"]:
        y = data["history"]["year"]
        data["history"]["year"] = {k: y[k] for k in ("combos", "pct_profitable_4", "pct_profitable_1")} | {
            "fixed_net4": y["fixed"]["net4"], "walk_net4": y["walk"]["net4"], "best_net4": y["best"]["net4"]}
    if (RES / "v2_grid.csv").exists():
        v2 = pd.read_csv(RES / "v2_grid.csv")
        data["history"]["v2"] = dict(combos=len(v2), pct_both=round(100 * ((v2.tr_net > 0) & (v2.te_net > 0)).mean(), 1),
                                     pct_train=round(100 * (v2.tr_net > 0).mean(), 1))
    cal = pd.read_csv(RES / "calibration.csv")
    errs = {}
    for c in ("cal", "trd", "mix70", "mix70v"):
        e = (cal[c + "_close"] - cal[c + "_open"]) - (cal.real_close - cal.real_open)
        errs[c] = dict(mean=round(float(e.mean()), 2), mae=round(float(e.abs().mean()), 2))
    data["calibration"] = dict(n=len(cal), errs=errs)

    blob = json.dumps(clean(data), separators=(",", ":"), default=str)
    html = (REP / "template_v3.html").read_text().replace("/*__CHARTS__*/", (REP / "charts.js").read_text()) \
        .replace("/*__DATA__*/", f"const D = {blob};")
    (REP / "index.html").write_text(html)
    print("report/index.html", len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
