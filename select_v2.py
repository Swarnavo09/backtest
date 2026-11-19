"""Pick the v2 setup using 2022-2024 only, then report its untouched 2025-2026 result.

    python select_v2.py      # after run_v2.py
"""
import json
from datetime import time
from pathlib import Path

import pandas as pd

import run_v2 as R
from strategy import add_signals_v2, backtest

OUT = Path(__file__).parent / "results"


def pick(g: pd.DataFrame) -> pd.DataFrame:
    """Train-only filter + score. No test-period column is used here."""
    ok = (g.tr_n >= 90) & (g.y2022 > 0) & (g.y2023 > 0) & (g.y2024 > 0) & (g.tr_pf >= 1.1)
    c = g[ok].copy()
    c["score"] = c.tr_net / (1 + c.tr_dd.abs() / 25000)
    return c.sort_values("score", ascending=False)


def neighbours(g: pd.DataFrame, row) -> pd.DataFrame:
    """Same rules, stop-loss one step either side: a robust setup should not fall off a cliff."""
    m = (g.sigset == row.sigset) & (g.bias == row.bias) & (g.st == row.st) & (g.exit_mode == row.exit_mode) \
        & (g.short_offset == row.short_offset) & (g.hedge == row.hedge) & (g.start == row.start)
    return g[m].sort_values("sl")


def monthly(tr: pd.DataFrame) -> list:
    m = tr.groupby(tr.entry_ts.dt.strftime("%Y-%m"))
    return [dict(month=k, trades=len(t), wins=int((t.net > 0).sum()), net=round(t.net.sum()),
                 net1=round(t.net_1lot.sum()), gross=round(t.gross.sum()), costs=round(t.costs.sum()))
            for k, t in m]


def main():
    g = pd.read_csv(OUT / "v2_grid.csv")
    cand = pick(g)
    print(f"{len(g)} combos; {len(cand)} pass the train-only filter")
    print(cand.head(15)[["sigset", "bias", "st", "sl", "exit_mode", "short_offset", "hedge", "start",
                         "tr_n", "tr_net", "tr_pf", "tr_dd", "te_n", "te_net", "te_pf", "te_dd"]].to_string(index=False))
    top = cand.head(20)
    print(f"top-20 by train score: {int((top.te_net > 0).sum())} of {len(top)} profitable in 2025-26")
    if cand.empty:
        return
    best = cand.iloc[0]
    st = tuple(float(x) for x in best.st.split(","))
    bars, vix = R.load()
    df = add_signals_v2(bars, best.sigset, best.bias, st=(int(st[0]), st[1]))
    hh, mm = map(int, best.start.split(":"))
    p = R.mk(sl=float(best.sl), exit_mode=best.exit_mode, short_offset=int(best.short_offset),
             hedge=int(best.hedge), start=time(hh, mm))
    tr = backtest(df, vix, p)
    tr.to_csv(OUT / "v2_trades_best.csv", index=False)
    res = dict(params={k: (v.item() if hasattr(v, "item") else v) for k, v in best.items()},
               monthly=monthly(tr), neighbours=neighbours(g, best).to_dict("records"),
               top20=top.to_dict("records"), n_pass=len(cand), combos=len(g),
               pct_train_pos=round(100 * (g.tr_net > 0).mean(), 1),
               pct_test_pos=round(100 * (g.te_net > 0).mean(), 1),
               pct_both_pos=round(100 * ((g.tr_net > 0) & (g.te_net > 0)).mean(), 1))
    (OUT / "v2_selected.json").write_text(json.dumps(res, indent=1, default=str))
    yr = tr.groupby(tr.entry_ts.dt.year).agg(trades=("net", "size"), net=("net", "sum"), net1=("net_1lot", "sum"))
    print(yr.round())


if __name__ == "__main__":
    main()
