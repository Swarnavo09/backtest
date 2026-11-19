"""Pick the v3 setup on 2022-2024 only, then stress-test it on 2025-2026.

    python select_v3.py      # after run_v3.py  -> results/v3_selected.json
"""
import json
from dataclasses import replace
from datetime import time

import pandas as pd

import realiv
import run_v2 as R
from strategy import add_signals_v2, backtest

import sys
CONV = sys.argv[1] if len(sys.argv) > 1 else "mix70v"
KEYS = ["sigset", "bias", "sl", "exit_mode", "short_offset", "hedge", "start", "dte0"]


def pick(g: pd.DataFrame) -> pd.DataFrame:
    """Train-only rules: profitable in each of 2022, 2023, 2024, enough trades, PF >= 1.15."""
    ok = (g.tr_n >= 90) & (g.y2022 > 0) & (g.y2023 > 0) & (g.y2024 > 0) & (g.tr_pf >= 1.15)
    c = g[ok].copy()
    c["score"] = c.tr_net / (1 + c.tr_dd.abs() / 25000)
    return c.sort_values("score", ascending=False)


def params_of(row, **over):
    hh, mm = map(int, str(row["start"]).split(":"))
    kw = dict(sl=float(row["sl"]), exit_mode=row["exit_mode"], short_offset=int(row["short_offset"]),
              hedge=int(row["hedge"]), start=time(hh, mm), dte0=bool(row["dte0"]))
    kw.update(over)
    return R.mk(**kw)


def monthly(tr):
    out = []
    for k, t in tr.groupby(tr.entry_ts.dt.strftime("%Y-%m")):
        out.append(dict(month=k, trades=len(t), wins=int((t.net > 0).sum()), net6=round(t.net.sum()),
                        net1=round(t.net_1lot.sum()), gross6=round(t.gross.sum()), costs6=round(t.costs.sum())))
    return out


def main():
    g = pd.read_csv(R.OUT / f"v3_grid_{CONV}.csv")
    cand = pick(g)
    print(f"{len(g)} combos; {len(cand)} pass the train-only filter")
    cols = KEYS + ["tr_n", "tr_net", "tr_pf", "tr_dd", "te_n", "te_net", "te_pf", "te_dd"]
    print(cand.head(20)[cols].to_string(index=False))
    top = cand.head(20)
    print(f"top-20 by train score: {int((top.te_net > 0).sum())} of {len(top)} profitable in 2025-26;"
          f" all {len(cand)} passing: {int((cand.te_net > 0).sum())} profitable in 2025-26")
    # Selection rule (2022-24 data only): the most common value of each setting among all
    # setups that pass the filter. A single top score tends to be a lucky spike; the
    # consensus is what the whole passing group agrees on.
    top1 = cand.iloc[0]
    cons = {k: cand[k].astype(str).value_counts().idxmax() for k in KEYS}
    m = pd.Series(True, index=g.index)
    for k, v in cons.items():
        m &= g[k].astype(str) == v
    best = g[m].iloc[0]
    bars, vix = R.load()
    df = add_signals_v2(bars, best.sigset, best.bias, st=(10, 3.0))
    realiv.install(CONV)
    p = params_of(best)
    tr = backtest(df, vix, p)
    tr.to_csv(R.OUT / f"v3_trades_best_{CONV}.csv", index=False)
    test = tr[tr.entry_ts.dt.strftime("%Y-%m-%d") > R.TRAIN_END]

    res = dict(params={k: (best[k].item() if hasattr(best[k], "item") else best[k]) for k in KEYS},
               rule="consensus of setups passing the 2022-24 filter",
               top1={k: (top1[k].item() if hasattr(top1[k], "item") else top1[k]) for k in cols},
               pass_test_quantiles={str(q): round(float(v)) for q, v in cand.te_net.quantile([.1, .25, .5, .75, .9]).items()},
               choice_counts={k: cand[k].astype(str).value_counts().to_dict() for k in KEYS},
               combos=len(g), n_pass=len(cand),
               pct_both_pos=round(100 * ((g.tr_net > 0) & (g.te_net > 0)).mean(), 1),
               top20=[{k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in cols} for _, r in top.iterrows()],
               top20_test_pos=int((top.te_net > 0).sum()), pass_test_pos=int((cand.te_net > 0).sum()),
               monthly=monthly(tr), train=R.stats(tr[tr.entry_ts.dt.strftime("%Y-%m-%d") <= R.TRAIN_END]),
               test=R.stats(test),
               years={int(k): round(v) for k, v in tr.groupby(tr.entry_ts.dt.year).net.sum().items()},
               reasons=tr.reason.value_counts().to_dict(),
               avg_credit=round(tr.credit.mean(), 1), avg_cost6=round(tr.costs.mean()),
               avg_sl_loss6=round(tr[tr.reason == "sl"].net.mean()) if (tr.reason == "sl").any() else 0,
               worst6=round(tr.net.min()), expiry_day_share=None)
    # how many trades were on expiry day
    res["expiry_day_trades"] = int(sum(1 for _, t in tr.iterrows()
                                       if realiv.install(CONV).expiry_fn(t.entry_ts, p) == t.entry_ts.date()
                                       and p.dte0))
    # stress tests on the SAME rules
    stress = {}
    for conv in ("calv", "mix60v", "mix70", "mix70v", "mix80v", "trdv"):
        realiv.install(conv)
        t = backtest(df, vix, p)
        d = t.entry_ts.dt.strftime("%Y-%m-%d")
        stress[conv] = dict(all=R.stats(t), test=R.stats(t[d > R.TRAIN_END]))
    realiv.install(CONV)
    for s in (0.25, 0.75, 1.0):
        t = backtest(df, vix, replace(p, slip=s))
        d = t.entry_ts.dt.strftime("%Y-%m-%d")
        stress[f"slip{s}"] = dict(all=R.stats(t), test=R.stats(t[d > R.TRAIN_END]))
    lots = {}
    for n in range(1, 7):
        t = backtest(df, vix, replace(p, lots=n))
        d = t.entry_ts.dt.strftime("%Y-%m-%d")
        lots[n] = dict(all=R.stats(t), test=R.stats(t[d > R.TRAIN_END]))
    res["stress"], res["lots"] = stress, lots
    # neighbours: change one setting at a time
    nb = []
    for k in ("sl", "exit_mode", "short_offset", "hedge", "start", "dte0", "bias", "sigset"):
        m = pd.Series(True, index=g.index)
        for kk in KEYS:
            if kk != k:
                m &= g[kk].astype(str) == str(best[kk])
        for _, r in g[m].iterrows():
            nb.append(dict(changed=k, value=str(r[k]), tr_net=r.tr_net, te_net=r.te_net, chosen=str(r[k]) == str(best[k])))
    res["neighbours"] = nb
    (R.OUT / f"v3_selected_{CONV}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("params", "train", "test", "years", "reasons", "avg_credit",
                                          "avg_cost6", "avg_sl_loss6", "worst6", "expiry_day_trades")}, indent=1, default=str))
    for k, v in stress.items():
        print(k, "all", v["all"]["net"], "test", v["test"]["net"], "pf", v["test"]["pf"])


if __name__ == "__main__":
    main()
