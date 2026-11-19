"""Positional NON-directional strategies (about 2-week and 4-week holds) on REAL NSE premiums, 2 lots.

Decisions on a day's close, executed at the next day's opening premium; time exit at the
close of the day before expiry. Stop-loss = loss of k x premium collected (checked at close).

    python positional_nondir.py   -> results/positional_nondir_grid.csv
"""
import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd

import positional as P

STRUCTS = {
    "short straddle": [(-1, 0, "C"), (-1, 0, "P")],
    "short strangle 400": [(-1, 400, "C"), (-1, -400, "P")],
    "short strangle 600": [(-1, 600, "C"), (-1, -600, "P")],
    "iron butterfly 500": [(-1, 0, "C"), (-1, 0, "P"), (+1, 500, "C"), (+1, -500, "P")],
    "iron condor 300/600": [(-1, 300, "C"), (-1, -300, "P"), (+1, 600, "C"), (+1, -600, "P")],
    "iron condor 500/800": [(-1, 500, "C"), (-1, -500, "P"), (+1, 800, "C"), (+1, -800, "P")],
}
HOLDS = {"2-week": (12, 16), "4-week": (19, 28)}
_G = {}


def _init():
    d, px, exps = P.load()
    vix = pd.read_csv(P.ROOT / "data" / "indiavix_1d_5y.csv", index_col=0, parse_dates=True)["Close"]
    vix.index = pd.to_datetime(vix.index).normalize()
    _G.update(d=d, px=px, exps=exps, vix=vix.reindex(d.index).ffill())


def run(struct, hold, sl_k, tgt, vix_max=None, weekday=None):
    d, px, exps, vix = _G["d"], _G["px"], _G["exps"], _G["vix"]
    days = list(d.index)
    lo, hi = HOLDS[hold]
    q = P.LOT * P.LOTS
    trades, pos = [], None
    for i in range(len(days) - 1):
        day, nxt = days[i], days[i + 1]
        if pos is not None:
            val, ok = 0.0, True
            for qm, K, k in pos["legs"]:
                p = px.get((day, pos["exp"], K, k))
                if p is None: ok = False; break
                val += qm * p[1]
            mtm = (val - pos["cost0"]) if ok else pos["last"]
            pos["last"] = mtm
            credit = -pos["cost0"]
            reason = None
            if sl_k is not None and mtm <= -sl_k * credit: reason = "sl"
            elif tgt is not None and mtm >= tgt * credit: reason = "target"
            elif nxt >= pos["exp"]: reason = "time"
            if reason:
                use_close = reason == "time"
                when = day if use_close else nxt
                ev, sp, bp, good = 0.0, 0.0, 0.0, True
                for qm, K, k in pos["legs"]:
                    p = px.get((when, pos["exp"], K, k)) or px.get((day, pos["exp"], K, k))
                    if p is None: good = False; break
                    pr = p[1] if use_close else p[0]
                    ev += qm * pr
                    if qm > 0: sp += abs(qm) * pr
                    else: bp += abs(qm) * pr
                if not good: ev = val
                n_orders = 2 * sum(abs(x[0]) for x in pos["legs"])
                cost = P.charges(pos["sell0"] + sp, pos["buy0"] + bp, n_orders) + P.SLIP * q * n_orders
                trades.append(dict(entry=pos["day"], exit=when, net=(ev - pos["cost0"]) * q - cost, reason=reason,
                                   credit=credit))
                pos = None
                continue
        if pos is None:
            if weekday is not None and nxt.weekday() != weekday:
                continue
            if vix_max is not None and vix.iloc[i] > vix_max:
                continue
            cands = [e for e in exps.get(nxt, []) if lo <= (e - nxt).days <= hi]
            if not cands:
                continue
            exp = cands[0]
            atm = round(d.Close.iloc[i] / 50) * 50
            legs = [(qm, float(atm + off), k) for qm, off, k in STRUCTS[struct]]
            cost0 = sell0 = buy0 = 0.0; good = True
            for qm, K, k in legs:
                p = px.get((nxt, exp, K, k))
                if p is None or p[2] < 20: good = False; break
                cost0 += qm * p[0]
                if qm > 0: buy0 += qm * p[0]
                else: sell0 += -qm * p[0]
            if good and cost0 < 0:
                pos = dict(day=nxt, exp=exp, legs=legs, cost0=cost0, sell0=sell0, buy0=buy0, last=0.0)
    return pd.DataFrame(trades)


def job(args):
    struct, hold, sl_k, tgt, vmax = args
    t = run(struct, hold, sl_k, tgt, vmax)
    if t.empty:
        return None
    tr, te = t[t.entry <= P.TRAIN_END], t[t.entry > P.TRAIN_END]
    yrs = t.groupby(t.entry.dt.year).net.sum().round().to_dict()
    return dict(struct=struct, hold=hold, sl=sl_k, tgt=tgt, vix_max=vmax,
                **{f"tr_{k}": v for k, v in P.stats(tr).items()}, **{f"te_{k}": v for k, v in P.stats(te).items()},
                **{f"all_{k}": v for k, v in P.stats(t).items()}, **{f"y{k}": v for k, v in yrs.items()})


def main():
    grid = list(itertools.product(STRUCTS, HOLDS, (None, 1.0, 1.5, 2.0), (None, 0.5, 0.7), (None, 18, 15)))
    with Pool(4, initializer=_init) as pool:
        res = [r for r in pool.map(job, grid) if r]
    g = pd.DataFrame(res)
    g.to_csv(P.OUT / "positional_nondir_grid.csv", index=False)
    ok = (g.y2022 > 0) & (g.y2023 > 0) & (g.y2024 > 0)
    print(len(g), "combos;", int(ok.sum()), "profitable each year 2022-24;", int((ok & (g.te_net > 0)).sum()), "also 2025-26")
    cols = ["struct", "hold", "sl", "tgt", "vix_max", "tr_n", "tr_net", "tr_dd", "te_net", "te_dd", "all_net", "all_pf", "all_win"]
    print(g[ok].sort_values("tr_net", ascending=False).head(20)[cols].to_string(index=False))
    for s in STRUCTS:
        for h in HOLDS:
            c = g[ok & (g.struct == s) & (g.hold == h)].sort_values("tr_net", ascending=False)
            if len(c):
                print(f"best {s} {h}:", c.iloc[0][cols].to_dict())


if __name__ == "__main__":
    main()
