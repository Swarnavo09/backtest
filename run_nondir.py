"""Intraday NON-directional option selling on Nifty, 2 lots, all costs.

Structures (strikes from ATM at entry):
  short straddle   : SELL ATM CE + SELL ATM PE                      (naked)
  short strangle   : SELL CE +200 + SELL PE -200                    (naked)
  iron butterfly   : SELL ATM CE/PE, BUY CE +300 / PE -300          (hedged)
  iron condor      : SELL CE +200 / PE -200, BUY CE +500 / PE -500  (hedged)
Pricing: real previous-day implied vol per strike (NSE bhavcopy), calibrated decay, VIX-driven IV.
Stop / target are a fraction of the premium collected at entry. Checked on 15-minute candles at
the candle's high and low (stop first if both).

    python run_nondir.py   -> results/nondir_grid.csv, results/nondir.json
"""
import itertools
import json
import math
from datetime import datetime, time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import realiv
import run_v2 as R
import strategy as S

LOTS = 2
Q = S.LOT_SIZE * LOTS
SLIP = 0.5
STRUCTS = {
    "short straddle": [(-1, 0, "C"), (-1, 0, "P")],
    "short strangle 200": [(-1, 200, "C"), (-1, -200, "P")],
    "iron butterfly 300": [(-1, 0, "C"), (-1, 0, "P"), (+1, 300, "C"), (+1, -300, "P")],
    "iron condor 200/500": [(-1, 200, "C"), (-1, -200, "P"), (+1, 500, "C"), (+1, -500, "P")],
}
ENTRIES = [time(9, 30), time(10, 0), time(10, 30), time(11, 0), time(12, 0), time(13, 0), time(14, 0)]
EXITS = [time(14, 45), time(15, 0), time(15, 15)]


class P0:
    def __init__(self, dte0): self.dte0 = dte0


_G = {}


def _init():
    bars, vix = R.load()
    _G["bars"] = bars
    _G["rv"] = realiv.install("mix70v")


def paths(args):
    """MTM path (rupees, 2 lots) for every day for one structure / entry time / dte0."""
    struct, et, dte0 = args
    bars, rv = _G["bars"], _G["rv"]
    out = []
    for day, g in bars.groupby(bars.index.date):
        g = g[g.index.time >= et]
        if g.empty or g.index[0].time() != et:
            continue
        t0 = g.index[0]
        exp = rv.expiry_fn(t0, P0(dte0))
        i = rv.day_pos.get(day)
        if exp is None or not i:
            continue
        prev = rv.days[i - 1]
        s0 = g.Open.iloc[0]
        atm = round(s0 / 50) * 50
        legs = [(q, atm + off, k) for q, off, k in STRUCTS[struct]]
        ivs = [rv.leg_iv(prev, exp, K, k) for _, K, k in legs]
        if any(v is None for v in ivs):
            continue

        def value(spot, ts):
            tt = ts.tz_localize(None).to_pydatetime()
            T = rv.T(tt, exp); kv = rv.vix_ratio(tt)
            return sum(q * S.bs_price(spot, K, T, iv * kv, k) for (q, K, k), iv in zip(legs, ivs))

        v0 = value(s0, t0)
        credit = -v0                                         # points collected (net)
        prem = [abs(S.bs_price(s0, K, rv.T(t0.tz_localize(None).to_pydatetime(), exp), iv, k)) for (_, K, k), iv in zip(legs, ivs)]
        rows = []
        for ts, b in g.iterrows():
            if ts.time() > time(15, 15):
                break
            mo = (value(b.Open, ts) - v0) * Q
            mh = (value(b.High, ts) - v0) * Q
            ml = (value(b.Low, ts) - v0) * Q
            rows.append((ts.time(), mo, min(mh, ml), max(mh, ml)))
        short_p = sum(p for (q, _, _), p in zip(legs, prem) if q < 0)
        long_p = sum(p for (q, _, _), p in zip(legs, prem) if q > 0)
        out.append(dict(day=day, exp_day=(exp == day), credit=credit, short_p=short_p, long_p=long_p,
                        nlegs=len(legs), s0=s0, path=rows))
    return (struct, et, dte0, out)


def apply(path_list, ext, sl, tg):
    res = []
    for d in path_list:
        cap = d["credit"] * Q
        slv = None if sl is None else -sl * cap
        tgv = None if tg is None else tg * cap
        pnl, reason = None, "time"
        for tm, mo, mw, mb in d["path"]:
            if tm >= ext:
                pnl = mo; break
            if slv is not None and mo <= slv: pnl, reason = mo, "sl"; break
            if tgv is not None and mo >= tgv: pnl, reason = mo, "target"; break
            if slv is not None and mw <= slv: pnl, reason = slv, "sl"; break
            if tgv is not None and mb >= tgv: pnl, reason = tgv, "target"; break
        if pnl is None:
            pnl = d["path"][-1][1]
        orders = 2 * d["nlegs"]
        # charges: sold premium at entry (short legs) + at exit (long legs ~ entry value); turnover ~2x premiums
        cost = S.charges(d["short_p"] + d["long_p"], d["short_p"] + d["long_p"], LOTS) * (orders / 4) \
            + SLIP * Q * orders
        res.append(dict(day=d["day"], exp_day=d["exp_day"], net=pnl - cost, reason=reason))
    return pd.DataFrame(res)


def stats(t):
    if t.empty:
        return dict(n=0, net=0, pf=0, dd=0, win=0)
    eq = t.net.cumsum(); w = t.net[t.net > 0].sum(); l = -t.net[t.net <= 0].sum()
    return dict(n=len(t), net=round(t.net.sum()), pf=round(w / l, 2) if l > 0 else 9.99,
                dd=round(float((eq - eq.cummax().clip(lower=0)).min())), win=round(100 * (t.net > 0).mean(), 1))


def grid_job(item):
    struct, et, dte0, pl = item
    rows = []
    for ext, sl, tg in itertools.product(EXITS, (None, 0.3, 0.5, 1.0), (None, 0.3, 0.5, 0.8)):
        if ext <= et:
            continue
        t = apply(pl, ext, sl, tg)
        t["day"] = pd.to_datetime(t.day)
        tr, te = t[t.day <= R.TRAIN_END], t[t.day > R.TRAIN_END]
        yrs = t.groupby(t.day.dt.year).net.sum().round().to_dict()
        rows.append(dict(struct=struct, entry=et.strftime("%H:%M"), exit=ext.strftime("%H:%M"), sl=sl, tgt=tg, dte0=dte0,
                         **{f"tr_{k}": v for k, v in stats(tr).items()}, **{f"te_{k}": v for k, v in stats(te).items()},
                         **{f"all_{k}": v for k, v in stats(t).items()}, **{f"y{k}": v for k, v in yrs.items()}))
    return rows


def main():
    jobs = list(itertools.product(STRUCTS, ENTRIES, (False, True)))
    with Pool(4, initializer=_init) as pool:
        P = pool.map(paths, jobs)
        import pickle
        pickle.dump(P, open(R.OUT / "nondir_paths.pkl", "wb"))
        rows = [r for chunk in pool.map(grid_job, P) for r in chunk]
    g = pd.DataFrame(rows)
    g.to_csv(R.OUT / "nondir_grid.csv", index=False)
    ok = (g.y2022 > 0) & (g.y2023 > 0) & (g.y2024 > 0)
    print(len(g), "combos;", int(ok.sum()), "profitable each year 2022-24;", int((ok & (g.te_net > 0)).sum()), "also in 2025-26")
    cols = ["struct", "entry", "exit", "sl", "tgt", "dte0", "tr_n", "tr_net", "te_net", "all_net", "all_dd", "all_pf", "all_win"]
    print(g[ok].sort_values("tr_net", ascending=False).head(20)[cols].to_string(index=False))
    for s in STRUCTS:
        c = g[ok & (g.struct == s)].sort_values("tr_net", ascending=False)
        if len(c):
            print(f"\nbest {s}:", c.iloc[0][cols].to_dict())


if __name__ == "__main__":
    main()
