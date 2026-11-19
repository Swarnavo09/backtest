"""VWAP version of the strategy vs the original week+today-open version, 1 vs 2 trades a day.

    python run_vwap.py     -> results/vwap_compare.json
"""
import itertools, json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import pandas as pd

import realiv
import run_v2 as R
from strategy import add_signals_v2, backtest

CONV = "mix70v"
BASE = dict(sl=120, exit_mode="hold", short_offset=0, hedge=300, start=time(9, 30), dte0=True)
_b = _v = None


def _init():
    global _b, _v
    _b, _v = R.load()


def summ(tr):
    d = tr.entry_ts.dt.strftime("%Y-%m-%d")
    yrs = {int(k): round(v) for k, v in tr.groupby(tr.entry_ts.dt.year).net.sum().items()}
    m = tr.groupby(tr.entry_ts.dt.strftime("%Y-%m")).net.sum()
    return dict(all=R.stats(tr), train=R.stats(tr[d <= R.TRAIN_END]), test=R.stats(tr[d > R.TRAIN_END]),
                years=yrs, months_up=int((m > 0).sum()), months=int(len(m)),
                last12=round(m.iloc[-12:].sum()), last12_up=int((m.iloc[-12:] > 0).sum()))


def run_one(args):
    bias, sigset, mt, extra = args
    df = add_signals_v2(_b, sigset, bias, st=(10, 3.0))
    p = R.mk(**{**BASE, **extra})
    p = replace(p, max_trades=mt)
    tr = backtest(df, _v, p)
    return dict(bias=bias, sigset=sigset, max_trades=mt, **{k: str(v) for k, v in extra.items()}, **summ(tr))


def grid_row(args):
    bias, sigset, sl, em, off = args
    df = add_signals_v2(_b, sigset, bias, st=(10, 3.0))
    p = R.mk(**{**BASE, "sl": sl, "exit_mode": em, "short_offset": off})
    tr = backtest(df, _v, p)
    d = tr.entry_ts.dt.strftime("%Y-%m-%d")
    y = tr.groupby(tr.entry_ts.dt.year).net.sum()
    return dict(bias=bias, sigset=sigset, sl=sl, exit_mode=em, short_offset=off,
                tr_net=round(tr[d <= R.TRAIN_END].net.sum()), te_net=round(tr[d > R.TRAIN_END].net.sum()),
                tr_pos_years=int(sum(y.get(k, 0) > 0 for k in (2022, 2023, 2024))))


def main():
    realiv.install(CONV)
    out = {}
    # 1) same rules as the chosen strategy, only the day filter swapped
    runs = [(b, "all3", mt, {}) for b in ("live", "vwap", "w_vwap", "none") for mt in (1, 2)]
    with Pool(4, initializer=_init) as pool:
        out["same_rules"] = pool.map(run_one, runs)
        # 2) re-tune the VWAP version on 2022-24 only (fair chance for VWAP)
        g = pool.map(grid_row, list(itertools.product(("vwap", "w_vwap"), ("st", "st_ema", "ema_macd", "all3"),
                                                      (45, 60, 80, 120), ("fixed", "trail", "hold"), (0, 100))))
    g = pd.DataFrame(g)
    g.to_csv(R.OUT / "vwap_grid.csv", index=False)
    out["grid"] = dict(n=len(g), pass3=int((g.tr_pos_years == 3).sum()),
                       pass3_test_pos=int(((g.tr_pos_years == 3) & (g.te_net > 0)).sum()))
    tuned = {}
    for b in ("vwap", "w_vwap"):
        c = g[(g.bias == b) & (g.tr_pos_years == 3)].sort_values("tr_net", ascending=False)
        if c.empty:
            c = g[g.bias == b].sort_values("tr_net", ascending=False)
        r = c.iloc[0]
        tuned[b] = dict(sigset=r.sigset, sl=int(r.sl), exit_mode=r.exit_mode, short_offset=int(r.short_offset),
                        all3_years_pos=int(r.tr_pos_years))
    with Pool(4, initializer=_init) as pool:
        out["tuned"] = pool.map(run_one, [(b, t["sigset"], mt, {"sl": t["sl"], "exit_mode": t["exit_mode"],
                                                                "short_offset": t["short_offset"]})
                                          for b, t in tuned.items() for mt in (1, 2)])
    (R.OUT / "vwap_compare.json").write_text(json.dumps(out, indent=1, default=str))
    for sec in ("same_rules", "tuned"):
        print("==", sec)
        for r in out[sec]:
            print(f"{r['bias']:7} {r['sigset']:8} max{r['max_trades']} {r.get('sl','120'):>4} {r.get('exit_mode','hold'):5}"
                  f" | all {r['all']['net']:>9} n{r['all']['n']:4} pf{r['all']['pf']} dd{r['all']['dd']:>9}"
                  f" | train {r['train']['net']:>8} test {r['test']['net']:>8} pf{r['test']['pf']} | yrs {r['years']} | last12 {r['last12']} ({r['last12_up']}/12 up)")
    print(out["grid"])


if __name__ == "__main__":
    main()
