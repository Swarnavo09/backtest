"""One-year, month-by-month backtest at 1 lot vs 4 lots, all MIS exits by 14:45.

    python fetch_upstox.py 2025-11-01 2026-11-18
    python run_year.py            # -> results/year_*.csv, results/year_summary.json

Three views of the same year:
  A. FIXED   - the 10-minute setup recommended from the first test, unchanged all year
  B. BEST    - the single best combination over the whole year (hindsight, optimistic)
  C. WALK    - each month trade the combination that did best over the previous
               3 months (no hindsight: this is what you could actually have done)
"""
from __future__ import annotations

import itertools
import json
from datetime import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import Params, add_indicators, backtest, htf_direction, load_bars, params_dict

ROOT = Path(__file__).parent
DATA, OUT = ROOT / "data", ROOT / "results"
LOTS = 4
EXIT_BY, LAST_ENTRY = time(14, 45), time(14, 0)
LOOKBACK = 3          # months used to choose next month's setup in the walk-forward

GRID = dict(
    tf=[5, 10, 15], ma=[(9, 21), (20, 50)], st=[(7, 3.0), (10, 3.0)], htf=[False, True],
    short_offset=[0, 100], hedge=[200, 300], sl=[30, 40, 50, 60],
    exit_mode=["fixed", "trail", "lock_ride"],
)
FIXED = dict(tf=10, ma_fast=9, ma_slow=21, st_period=7, st_mult=3.0, macd_zero=False, sl=60,
             exit_mode="trail", short_offset=100, htf=True, max_trades=2, hedge=200)

_bars = _htf = _vix = None


def load():
    vix = pd.read_csv(DATA / "indiavix_1d_1y.csv", index_col=0, parse_dates=True)["Close"]
    vix.index = pd.to_datetime(vix.index).normalize()
    bars = {}
    for tf in (5, 10, 15):
        b = load_bars(DATA / "nifty_5m_1y.csv", tf)
        full = b.groupby(b.index.date).size()
        keep = set(full[full >= 0.9 * full.max()].index)          # drop special/short sessions
        bars[tf] = b[[d in keep for d in b.index.date]]
    return bars, htf_direction(bars[5]), vix


def _init():
    global _bars, _htf, _vix
    _bars, _htf, _vix = load()


def mk(**kw) -> Params:
    return Params(squareoff=EXIT_BY, last_entry=LAST_ENTRY, lots=LOTS, **kw)


def run_key(key):
    tf, ma, st, hf = key
    base = mk(tf=tf, ma_fast=ma[0], ma_slow=ma[1], st_period=st[0], st_mult=st[1], htf=hf)
    df = add_indicators(_bars[tf], base, _htf)
    rows = []
    for off, hedge, sl, em in itertools.product(GRID["short_offset"], GRID["hedge"], GRID["sl"], GRID["exit_mode"]):
        p = mk(tf=tf, ma_fast=ma[0], ma_slow=ma[1], st_period=st[0], st_mult=st[1], htf=hf,
               short_offset=off, hedge=hedge, sl=sl, exit_mode=em)
        tr = backtest(df, _vix, p)
        if tr.empty:
            continue
        m = tr.groupby(tr.entry_ts.dt.strftime("%Y-%m"))
        month = pd.DataFrame({"net4": m.net.sum(), "net1": m.net_1lot.sum(), "trades": m.size()})
        rows.append((params_dict(p), month.reset_index().rename(columns={"entry_ts": "month"}).to_dict("records")))
    return rows


def monthly(tr: pd.DataFrame, months) -> list:
    g = tr.groupby(tr.entry_ts.dt.strftime("%Y-%m"))
    out = []
    for mo in months:
        if mo in g.groups:
            t = g.get_group(mo)
            out.append(dict(month=mo, trades=len(t), wins=int((t.net > 0).sum()),
                            net1=round(t.net_1lot.sum()), net4=round(t.net.sum()),
                            gross4=round(t.gross.sum()), costs4=round(t.costs.sum())))
        else:
            out.append(dict(month=mo, trades=0, wins=0, net1=0, net4=0, gross4=0, costs4=0))
    return out


def trade_stats(tr: pd.DataFrame) -> dict:
    eq = tr.net.cumsum()
    sl = tr[tr.reason == "sl"]
    return dict(dd_trades=round(float((eq - eq.cummax().clip(lower=0)).min())),
                avg_sl_loss=round(float(sl.net.mean())) if len(sl) else 0,
                worst_trade=round(float(tr.net.min())))


def max_dd(series) -> float:
    eq = np.cumsum(series)
    return float((eq - np.maximum.accumulate(np.maximum(eq, 0))).min()) if len(eq) else 0.0


def main() -> None:
    OUT.mkdir(exist_ok=True)
    bars, htf, vix = load()
    days = sorted(set(bars[5].index.date))
    months = sorted({d.strftime("%Y-%m") for d in days})
    print(f"{len(days)} sessions, {months[0]} -> {months[-1]}")

    # ---------------------------------------------------------------- grid
    keys = list(itertools.product(GRID["tf"], GRID["ma"], GRID["st"], GRID["htf"]))
    with Pool(4, initializer=_init) as pool:
        res = [r for chunk in pool.map(run_key, keys) for r in chunk]
    recs, mrows = [], []
    for i, (pd_, mon) in enumerate(res):
        mm = {r["month"]: r for r in mon}
        net4 = [mm.get(mo, {}).get("net4", 0.0) for mo in months]
        net1 = [mm.get(mo, {}).get("net1", 0.0) for mo in months]
        recs.append(dict(id=i, **pd_, trades=sum(r["trades"] for r in mon),
                         net4=round(sum(net4)), net1=round(sum(net1)),
                         months_up4=sum(v > 0 for v in net4), dd4=round(max_dd(net4))))
        for mo, a, b in zip(months, net4, net1):
            mrows.append(dict(id=i, month=mo, net4=a, net1=b, trades=mm.get(mo, {}).get("trades", 0)))
    grid, mtab = pd.DataFrame(recs), pd.DataFrame(mrows)
    grid.to_csv(OUT / "year_grid.csv", index=False)
    mtab.to_csv(OUT / "year_grid_monthly.csv", index=False)
    print(f"{len(grid)} combinations; profitable at 4 lots: {(grid.net4 > 0).mean():.1%}, at 1 lot: {(grid.net1 > 0).mean():.1%}")

    def trades_for(row) -> pd.DataFrame:
        p = mk(tf=int(row["tf"]), ma_fast=int(row["ma_fast"]), ma_slow=int(row["ma_slow"]),
               st_period=int(row["st_period"]), st_mult=float(row["st_mult"]), htf=bool(row["htf"]),
               short_offset=int(row["short_offset"]), hedge=int(row["hedge"]), sl=float(row["sl"]),
               exit_mode=row["exit_mode"], max_trades=int(row.get("max_trades", 2)),
               macd_zero=bool(row.get("macd_zero", False)))
        return backtest(add_indicators(bars[p.tf], p, htf), vix, p)

    out = {"sessions": len(days), "first": str(days[0]), "last": str(days[-1]), "months": months,
           "lots": LOTS, "exit_by": "14:45", "last_entry": "14:00", "combos": len(grid),
           "pct_profitable_4": round(100 * (grid.net4 > 0).mean(), 1),
           "pct_profitable_1": round(100 * (grid.net1 > 0).mean(), 1),
           "median_net4": round(grid.net4.median()), "median_net1": round(grid.net1.median())}

    # ------------------------------------------------------------- A. fixed
    trA = trades_for(FIXED)
    trA.to_csv(OUT / "year_trades_fixed.csv", index=False)
    out["fixed"] = dict(params=FIXED, monthly=monthly(trA, months), trades=len(trA),
                        net1=round(trA.net_1lot.sum()), net4=round(trA.net.sum()),
                        cost_per_lot_1=round(trA.costs_1lot.mean()),
                        cost_per_lot_4=round((trA.costs / LOTS).mean()),
                        gross_per_lot=round((trA.gross / LOTS).mean()),
                        win_rate=round(100 * (trA.net > 0).mean(), 1), **trade_stats(trA))

    # ---------------------------------------------- B. best over the year
    best = grid.sort_values("net4", ascending=False).iloc[0]
    trB = trades_for(best)
    trB.to_csv(OUT / "year_trades_best.csv", index=False)
    out["best"] = dict(params={k: best[k] for k in ("tf", "ma_fast", "ma_slow", "st_period", "st_mult", "htf",
                                                    "short_offset", "hedge", "sl", "exit_mode")},
                       monthly=monthly(trB, months), trades=len(trB),
                       net1=round(trB.net_1lot.sum()), net4=round(trB.net.sum()),
                       win_rate=round(100 * (trB.net > 0).mean(), 1), **trade_stats(trB))
    out["per_tf"] = {int(tf): dict(best_net4=round(g.net4.max()), median_net4=round(g.net4.median()),
                                   pct_profitable_4=round(100 * (g.net4 > 0).mean(), 1))
                     for tf, g in grid.groupby("tf")}

    # ------------------------------------------------------- C. walk-forward
    piv4 = mtab.pivot(index="id", columns="month", values="net4")[months]
    piv1 = mtab.pivot(index="id", columns="month", values="net1")[months]
    pivt = mtab.pivot(index="id", columns="month", values="trades")[months]
    walk = []
    for k in range(LOOKBACK, len(months)):
        look = months[k - LOOKBACK:k]
        ok = pivt[look].sum(axis=1) >= 8
        score = piv4.loc[ok, look].sum(axis=1)
        pick = int(score.idxmax())
        mo = months[k]
        g = grid.set_index("id").loc[pick]
        walk.append(dict(month=mo, pick=pick, lookback_net4=round(score.max()),
                         net4=round(piv4.loc[pick, mo]), net1=round(piv1.loc[pick, mo]),
                         trades=int(pivt.loc[pick, mo]),
                         setup=f"{int(g.tf)}m EMA{int(g.ma_fast)}/{int(g.ma_slow)} ST{int(g.st_period)},{g.st_mult:g} "
                               f"{'1h ' if g.htf else ''}{'ITM100' if g.short_offset else 'ATM'} H{int(g.hedge)} "
                               f"SL{int(g.sl)} {g.exit_mode}"))
    out["walk"] = dict(lookback=LOOKBACK, monthly=walk,
                       net4=round(sum(w["net4"] for w in walk)), net1=round(sum(w["net1"] for w in walk)))

    (OUT / "year_summary.json").write_text(json.dumps(out, indent=2, default=str))
    for name in ("fixed", "best"):
        print(name, out[name]["params"], "net1", out[name]["net1"], "net4", out[name]["net4"])
    print("walk", out["walk"]["net1"], out["walk"]["net4"])


if __name__ == "__main__":
    main()
