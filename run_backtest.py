"""Grid-search the hedged Nifty spread strategy on 5, 10 and 15 minute candles.

    python run_backtest.py            # writes results/*.csv and results/summary.json

Stage 1 tests the strategy exactly as described (ATM short leg, 200-pt hedge).
Stage 2 adds the structural fixes the stage-1 diagnosis pointed to:
strike offset (sell ITM/OTM), a 1-hour Supertrend filter and max trades/day.

Every combination keeps target = 2 x stop-loss (1:2). The first 2/3 of the
sessions pick the parameters (in-sample); the last 1/3 is held back to check
them (out-of-sample). Only out-of-sample numbers say whether a setup works.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from strategy import (Params, add_indicators, backtest, htf_direction, load_bars,
                      params_dict, summarize)

ROOT = Path(__file__).parent
DATA, OUT = ROOT / "data", ROOT / "results"

STAGE1 = dict(
    tf=[5, 10, 15], ma=[(9, 21), (20, 50)], st=[(10, 3.0), (10, 2.0), (7, 3.0)],
    macd_zero=[False, True], sl=[20, 25, 30, 40, 50, 60],
    exit_mode=["fixed", "be", "step", "trail", "lock_ride"], st_exit=[False, True],
    short_offset=[0], htf=[False], max_trades=[2],
)
STAGE2 = dict(
    tf=[5, 10, 15], ma=[(9, 21), (20, 50)], st=[(10, 3.0), (10, 2.0), (7, 3.0)],
    macd_zero=[False, True], sl=[30, 40, 50, 60],
    exit_mode=["fixed", "be", "step", "trail", "lock_ride"], st_exit=[False],
    short_offset=[-100, 0, 100], htf=[False, True], max_trades=[1, 2],
)
MIN_TRADES_IS = 12


def load_vix() -> pd.Series:
    v = pd.read_csv(DATA / "indiavix_1d.csv", index_col=0, parse_dates=True)["Close"]
    v.index = pd.to_datetime(v.index).normalize()
    return v


def load_all():
    vix = load_vix()
    bars = {tf: load_bars(DATA / "nifty_5m.csv", tf) for tf in (5, 10, 15)}
    last_day = bars[5].index[-1].date()
    if (bars[5].index.date == last_day).sum() < 75:          # unfinished session
        bars = {tf: b[b.index.date != last_day] for tf, b in bars.items()}
    htf = htf_direction(bars[5])
    days = sorted(set(bars[5].index.date))
    split = days[int(len(days) * 2 / 3)]
    return vix, bars, htf, days, split


def run_grid(grid_def, vix, bars, htf, days, split) -> pd.DataFrame:
    rows, cache = [], {}
    n_is = sum(1 for x in days if x < split)
    for tf, ma, st, mz, sl, em, se, off, hf, mt in itertools.product(*grid_def.values()):
        p = Params(tf=tf, ma_fast=ma[0], ma_slow=ma[1], st_period=st[0], st_mult=st[1],
                   macd_zero=mz, sl=sl, exit_mode=em, st_exit=se, short_offset=off,
                   htf=hf, max_trades=mt)
        key = (tf, ma, st, mz, hf)
        if key not in cache:
            cache[key] = add_indicators(bars[tf], p, htf)
        tr = backtest(cache[key], vix, p)
        if tr.empty:
            continue
        d = tr.entry_ts.dt.date
        row = params_dict(p)
        row.update({f"all_{k}": v for k, v in summarize(tr, len(days)).items()})
        row.update({f"is_{k}": v for k, v in summarize(tr[d < split], n_is).items()})
        row.update({f"oos_{k}": v for k, v in summarize(tr[d >= split], len(days) - n_is).items()})
        row["gross"] = round(tr.gross.sum(), 0)
        row["costs"] = round(tr.costs.sum(), 0)
        row["spot_pts"] = round(tr.spot_pts.sum(), 0)
        rows.append(row)
    return pd.DataFrame(rows)


def to_params(r) -> Params:
    return Params(tf=int(r.tf), ma_fast=int(r.ma_fast), ma_slow=int(r.ma_slow),
                  st_period=int(r.st_period), st_mult=float(r.st_mult),
                  macd_zero=bool(r.macd_zero), sl=float(r.sl), exit_mode=r.exit_mode,
                  st_exit=bool(r.st_exit), short_offset=int(r.short_offset),
                  htf=bool(r.htf), max_trades=int(r.max_trades))


def pick(grid: pd.DataFrame, tf: int):
    g = grid[(grid.tf == tf) & (grid.is_trades >= MIN_TRADES_IS)].copy()
    g["score"] = g.is_net / (1 + g.is_max_dd.abs() / 1000)    # in-sample only
    return g.sort_values("score", ascending=False).iloc[0].drop("score")


def describe_stage(name, grid, vix, bars, htf, days):
    out = {}
    for tf in (5, 10, 15):
        best = pick(grid, tf)
        g_all = grid[grid.tf == tf]
        p = to_params(best)
        tr = backtest(add_indicators(bars[tf], p, htf), vix, p)
        tr.to_csv(OUT / f"trades_{name}_{tf}m.csv", index=False)
        out[tf] = dict(
            best=best.to_dict(),
            combos=len(g_all),
            pct_profitable_all=round(100 * (g_all.all_net > 0).mean(), 1),
            pct_profitable_oos=round(100 * (g_all.oos_net > 0).mean(), 1),
            median_all_net=round(g_all.all_net.median(), 0),
            hedge={w: summarize(backtest(add_indicators(bars[tf], p, htf), vix,
                                         replace(p, hedge=w)), len(days))
                   for w in (100, 200, 300)},
            slippage={s: summarize(backtest(add_indicators(bars[tf], p, htf), vix,
                                            replace(p, slip=s)), len(days))
                      for s in (0.0, 0.25, 0.5, 1.0)},
        )
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    vix, bars, htf, days, split = load_all()
    print(f"{len(days)} sessions {days[0]} -> {days[-1]}; out-of-sample from {split}")
    summary = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]),
                   oos_from=str(split), n_is=sum(1 for x in days if x < split))
    for name, gd in (("stage1", STAGE1), ("stage2", STAGE2)):
        grid = run_grid(gd, vix, bars, htf, days, split)
        grid.to_csv(OUT / f"grid_{name}.csv", index=False)
        print(f"{name}: {len(grid)} combinations")
        summary[name] = describe_stage(name, grid, vix, bars, htf, days)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
