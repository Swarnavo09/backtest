"""Synthetic future vs hedged spread on the same signals.

Synthetic long  = BUY ATM CE + SELL ATM PE   (bullish signal)
Synthetic short = BUY ATM PE + SELL ATM CE   (bearish signal)
Stop / target in Nifty points (the position moves ~1:1 with Nifty). Legs priced with real
implied vols (previous NSE close), calibrated decay and VIX-driven IV; full costs.

    python run_synthetic.py   -> results/synthetic.json
"""
import itertools
import json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import realiv
import run_ar_filters as AF
import run_exits as E
import run_trailing as T
import run_v2 as R
import run_vwap as V
import strategy as S
from strategy import add_signals_v2, backtest

SQ = time(15, 0)
_ctx = {}


def _init():
    T._init()
    rv = realiv.install("mix70v")
    for filt in ("30m EMA 9/21", "none"):
        df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
        if filt != "none":
            f = AF.filt(filt, df)
            df["bull"] &= f[0]; df["bear"] &= f[1]
        el, es = E.exit_arrays(df, "30m EMA 9/21 flips")
        p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0)
        tr = backtest(df, AF._v, p)
        legs = []
        for t in tr.itertuples():
            side = 1 if t.side == "BULL PUT" else -1
            K = round(t.spot_in / 50) * 50
            exp = S.PRICING["expiry"](t.entry_ts, p)
            d = t.entry_ts.date()
            i = rv.day_pos.get(d)
            prev = rv.days[i - 1] if i else None
            ivc = rv.leg_iv(prev, exp, K, "C") if prev else None
            ivp = rv.leg_iv(prev, exp, K, "P") if prev else None
            legs.append((t.entry_ts, side, t.spot_in, K, exp, ivc, ivp))
        _ctx[filt] = (df, el, es, legs, rv)


def value(rv, spot, ts, K, exp, ivc, ivp, side):
    t = ts.tz_localize(None).to_pydatetime()
    Ty = rv.T(t, exp)
    k = rv.vix_ratio(t)
    c = S.bs_price(spot, K, Ty, ivc * k, "C")
    p = S.bs_price(spot, K, Ty, ivp * k, "P")
    return c, p


def sim(filt, sl, rr, use_exit, lots, slip=0.5):
    df, el, es, legs, rv = _ctx[filt]
    q = S.LOT_SIZE * lots
    idx = df.index
    pos = {t: i for i, t in enumerate(idx)}
    O, H, L, C = df.Open.values, df.High.values, df.Low.values, df.Close.values
    out = []
    for ets, side, s0, K, exp, ivc, ivp in legs:
        if ivc is None or ivp is None:
            continue
        c0, p0 = value(rv, s0, ets, K, exp, ivc, ivp, side)
        tgt = None if rr is None else rr * sl
        i = pos[ets]; reason = "time"; s_exit = None; ts_exit = None
        exc = el if side == 1 else es
        while i < len(idx):
            ts = idx[i]
            if ts.time() >= SQ or ts.date() != ets.date():
                s_exit, ts_exit = O[i], ts; break
            o = O[i]
            adverse = (s0 - L[i]) if side == 1 else (H[i] - s0)
            fav = (H[i] - s0) if side == 1 else (s0 - L[i])
            if (s0 - o) * side >= sl:
                s_exit, ts_exit, reason = o, ts, "sl"; break
            if tgt is not None and (o - s0) * side >= tgt:
                s_exit, ts_exit, reason = o, ts, "target"; break
            if adverse >= sl:
                s_exit, ts_exit, reason = s0 - side * sl, ts, "sl"; break
            if tgt is not None and fav >= tgt:
                s_exit, ts_exit, reason = s0 + side * tgt, ts, "target"; break
            if use_exit and exc[i] and i + 1 < len(idx) and idx[i + 1].date() == ts.date():
                s_exit, ts_exit, reason = O[i + 1], idx[i + 1], "exit_rule"; break
            i += 1
        if s_exit is None:
            s_exit, ts_exit = C[i - 1], idx[i - 1]
        c1, p1 = value(rv, s_exit, ts_exit, K, exp, ivc, ivp, side)
        if side == 1:      # long CE, short PE
            gross = ((c1 - c0) + (p0 - p1)) * q
            sell_prem, buy_prem = p0 + c1, c0 + p1
        else:              # long PE, short CE
            gross = ((p1 - p0) + (c0 - c1)) * q
            sell_prem, buy_prem = c0 + p1, p0 + c1
        cost = S.charges(sell_prem, buy_prem, lots) + 4 * slip * q
        out.append(dict(entry_ts=ets, net=gross - cost, reason=reason, pts=(s_exit - s0) * side))
    r = pd.DataFrame(out)
    r["net_1lot"] = r.net / lots
    return r


def spread(filt, lots):
    df, el, es, _, _ = _ctx[filt]
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, lots=lots)
    tr = backtest(df, AF._v, p)
    return E.simulate(df, tr, replace(p, squareoff=SQ), el, es, 3000 * lots)


def summarize(r):
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    last2 = r[r.entry_ts.dt.strftime("%Y-%m-%d") > "2024-11-18"]
    return dict(train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                last2y=R.stats(last2), years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                worst_day=round(r.net.min()), reasons=r.reason.value_counts().to_dict())


def job(args):
    filt, sl, rr, ue = args
    r = sim(filt, sl, rr, ue, 1)
    return dict(filter=filt, sl=sl, rr=rr, exit_rule=ue, **summarize(r))


def main():
    grid = list(itertools.product(("30m EMA 9/21", "none"), (30, 40, 50, 60, 80, 100, 120),
                                  (None, 1.0, 1.5, 2.0, 3.0), (True, False)))
    with Pool(4, initializer=_init) as pool:
        res = pool.map(job, grid)
    g = pd.DataFrame([dict(filter=r["filter"], sl=r["sl"], rr=r["rr"], exit_rule=r["exit_rule"], train=r["train"]["net"],
                           test=r["test"]["net"], last2y=r["last2y"]["net"], all=r["all"]["net"], dd=r["all"]["dd"],
                           pf=r["all"]["pf"], neg=sum(v < 0 for v in r["years"].values())) for r in res])
    g.to_csv(R.OUT / "synthetic_grid.csv", index=False)
    print("Synthetic future, 1 lot. Top by 2022-24 (train) profit:")
    print(g.sort_values("train", ascending=False).head(12).to_string(index=False))
    print("\nrequested 1:2 and 1:3 only, top by train:")
    print(g[g.rr.isin([2.0, 3.0])].sort_values("train", ascending=False).head(8).to_string(index=False))
    # chosen synthetic (best train) at 1 and 2 lots, and spreads at 1 and 2 lots
    best = g.sort_values("train", ascending=False).iloc[0]
    best12 = g[g.rr.isin([2.0, 3.0])].sort_values("train", ascending=False).iloc[0]
    _init()
    final = {}
    for lots in (1, 2):
        for label, b in (("synthetic best", best), ("synthetic 1:2/1:3", best12)):
            final[f"{label} · {lots} lot"] = dict(params=b.to_dict(), **summarize(
                sim(b["filter"], int(b.sl), None if pd.isna(b.rr) else float(b.rr), bool(b.exit_rule), lots)))
        final[f"spread (ATM/OTM300) · {lots} lot"] = summarize(spread("30m EMA 9/21", lots))
        final[f"synthetic every signal, no filter, SL80 1:2 · {lots} lot"] = summarize(sim("none", 80, 2.0, True, lots))
    (R.OUT / "synthetic.json").write_text(json.dumps(dict(grid=g.to_dict("records"), final=final), indent=1, default=str))
    print("\nComparison:")
    for k, v in final.items():
        print(f"  {k:52} | all {v['all']['net']:>9} dd {v['all']['dd']:>9} pf {v['all']['pf']} win {v['all']['win']} | "
              f"train {v['train']['net']:>8} test {v['test']['net']:>8} last2y {v['last2y']['net']:>8} | worst day {v['worst_day']} | {v['years']}")


if __name__ == "__main__":
    main()
