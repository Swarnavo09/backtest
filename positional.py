"""Positional (about two-week) hedged Nifty option strategies, priced with REAL NSE premiums.

Every decision is made on a day's close and executed at the NEXT day's opening premium
(bhavcopy OPEN) for every leg; time exits use the day-before-expiry close. Signals come from
daily / weekly / monthly candles of Nifty spot.

    python fetch_bhav.py with NEXP=4  ->  data/nifty_opt_bhav_4exp.csv.gz
    python positional.py              ->  results/positional_grid.csv, results/positional.json
"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import ema, supertrend

ROOT = Path(__file__).parent
OUT = ROOT / "results"
LOT = 65
LOTS = 2
SLIP = 1.0                    # points per leg per side (positional, wider strikes)
TRAIN_END = pd.Timestamp("2024-12-31")


# ----------------------------------------------------------------- data
def load():
    n5 = pd.read_csv(ROOT / "data" / "nifty_5m_5y.csv", index_col=0, parse_dates=True)
    n5.index = pd.to_datetime(n5.index, utc=True).tz_convert("Asia/Kolkata")
    d = n5.groupby(n5.index.date).agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
                                     Close=("Close", "last"), n=("Close", "size"))
    d = d[d.n >= 60].drop(columns="n")
    d.index = pd.to_datetime(d.index)
    o = pd.read_csv(ROOT / "data" / "nifty_opt_bhav_4exp.csv.gz", parse_dates=["date", "expiry"])
    o = o[(o.close > 0)]
    px = {}
    for r in o.itertuples(index=False):
        px[(r.date, r.expiry, float(r.strike), r.type[0])] = (r.open if r.open > 0 else r.close, r.close, r.volume)
    exps = o.groupby("date").expiry.apply(lambda s: sorted(set(s))).to_dict()
    return d, px, exps


def indicators(d: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=d.index)
    x["d_st"], _ = supertrend(d, 10, 3.0)
    e20, e50 = ema(d.Close, 20), ema(d.Close, 50)
    x["d_ema"] = np.where((e20 > e50) & (d.Close > e20), 1, np.where((e20 < e50) & (d.Close < e20), -1, 0))
    # live weekly / monthly candles as of each day (no look-ahead: only data up to that close)
    wk = d.index.to_period("W-SUN"); mo = d.index.to_period("M")
    x["w_col"] = np.sign(d.Close - d.Open.groupby(wk).transform("first"))
    x["m_col"] = np.sign(d.Close - d.Open.groupby(mo).transform("first"))
    # weekly supertrend / EMA on completed weeks + the live week
    wkdf = d.groupby(wk).agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
    st_live, ema_live = [], []
    weeks = list(wkdf.index)
    wpos = {w: i for i, w in enumerate(weeks)}
    # recompute on the fly for the live (partial) week: cheap enough on daily data
    for day, w in zip(d.index, wk):
        k = wpos[w]
        hist = wkdf.iloc[:k].copy()
        cur = d.loc[(wk == w) & (d.index <= day)]
        live = pd.DataFrame({"Open": [cur.Open.iloc[0]], "High": [cur.High.max()], "Low": [cur.Low.min()],
                             "Close": [cur.Close.iloc[-1]]}, index=[w])
        ww = pd.concat([hist, live])
        if len(ww) < 12:
            st_live.append(0); ema_live.append(0); continue
        sd, _ = supertrend(ww, 10, 3.0)
        st_live.append(int(sd.iloc[-1]))
        ema_live.append(1 if ww.Close.iloc[-1] > ema(ww.Close, 10).iloc[-1] else -1)
    x["w_st"] = st_live
    x["w_ema"] = ema_live
    return x


BIASES = {
    "Daily Supertrend": ["d_st"],
    "Daily + Weekly Supertrend": ["d_st", "w_st"],
    "Daily EMA 20/50 + Weekly EMA 10": ["d_ema", "w_ema"],
    "Daily ST + week & month candle": ["d_st", "w_col", "m_col"],
    "Weekly ST + month candle": ["w_st", "m_col"],
    "Daily ST + Weekly ST + month candle": ["d_st", "w_st", "m_col"],
}


def bias_series(x, cols):
    v = x[cols].values
    bull = (v > 0).all(axis=1); bear = (v < 0).all(axis=1)
    return np.where(bull, 1, np.where(bear, -1, 0))


# -------------------------------------------------------------- structures
# legs: list of (qty multiplier, strike offset in the trade direction, kind) ; +qty = buy, -qty = sell
def legs_for(struct, side):
    k = "C" if side == 1 else "P"          # trend-side option
    ko = "P" if side == 1 else "C"         # option on the other side
    s = side
    if struct == "credit ATM/300":     return [(-1, 0, ko), (+1, -300 * s, ko)]
    if struct == "credit ATM/500":     return [(-1, 0, ko), (+1, -500 * s, ko)]
    if struct == "credit OTM100/400":  return [(-1, -100 * s, ko), (+1, -400 * s, ko)]
    if struct == "debit ATM/300":      return [(+1, 0, k), (-1, 300 * s, k)]
    if struct == "debit ATM/500":      return [(+1, 0, k), (-1, 500 * s, k)]
    if struct == "broken-wing fly 1:2 (0/200/500)": return [(+1, 0, k), (-2, 200 * s, k), (+1, 500 * s, k)]
    if struct == "broken-wing fly 1:2 (0/300/700)": return [(+1, 0, k), (-2, 300 * s, k), (+1, 700 * s, k)]
    if struct == "skewed condor": return [(-1, 0, ko), (+1, -300 * s, ko), (-1, 500 * s, k), (+1, 800 * s, k)]
    raise ValueError(struct)


STRUCTS = ["credit ATM/300", "credit ATM/500", "credit OTM100/400", "debit ATM/300", "debit ATM/500",
           "broken-wing fly 1:2 (0/200/500)", "broken-wing fly 1:2 (0/300/700)", "skewed condor"]


def expiry_payoff(legs_abs, S):
    v = 0.0
    for q, K, kind in legs_abs:
        v += q * (max(S - K, 0) if kind == "C" else max(K - S, 0))
    return v


def charges(sell_prem, buy_prem, orders, lots=LOTS):
    qn = LOT * lots
    turnover = (sell_prem + buy_prem) * qn
    brokerage = 20.0 * orders
    stt = 0.001 * sell_prem * qn
    txn = 0.0003503 * turnover
    sebi = turnover * 10 / 1e7
    stamp = 0.00003 * buy_prem * qn
    return brokerage + stt + txn + sebi + stamp + 0.18 * (brokerage + txn + sebi)


# ----------------------------------------------------------------- engine
def run(d, x, px, exps, bias_name, struct, sl_pct, tgt_frac, reentry, flip_exit, min_dte=8, re_dte=4):
    bias = bias_series(x, BIASES[bias_name])
    days = list(d.index)
    q = LOT * LOTS
    trades = []
    pos = None
    last_exit = None            # (day index, reason, expiry)
    prev_b = 0
    for i in range(len(days) - 1):
        day, nxt = days[i], days[i + 1]
        b = bias[i]
        # -------- manage open position at this close; act at next open
        if pos is not None:
            S = d.Close.iloc[i]
            adverse = (pos["S0"] - S) / pos["S0"] * pos["side"]
            val = 0.0; ok = True
            for qm, K, kind in pos["legs"]:
                p = px.get((day, pos["exp"], K, kind))
                if p is None:
                    ok = False; break
                val += qm * p[1]
            mtm = (val - pos["cost0"]) if ok else pos.get("last_mtm", 0.0)
            pos["last_mtm"] = mtm
            reason = None
            if sl_pct is not None and adverse >= sl_pct:
                reason = "sl"
            elif tgt_frac is not None and pos["maxp"] > 0 and mtm >= tgt_frac * pos["maxp"]:
                reason = "target"
            elif flip_exit and b == -pos["side"]:
                reason = "flip"
            day_before_exp = (nxt >= pos["exp"])           # next trading day is expiry day (or later)
            if reason is None and day_before_exp:
                reason = "time"
            if reason:
                # time exit at today's close; others at next open
                use_close = reason == "time"
                when = day if use_close else nxt
                exit_val = 0.0; sell_p = buy_p = 0.0; good = True
                for qm, K, kind in pos["legs"]:
                    p = px.get((when, pos["exp"], K, kind))
                    if p is None:
                        p = px.get((day, pos["exp"], K, kind))
                    if p is None:
                        good = False; break
                    price = p[1] if use_close else p[0]
                    exit_val += qm * price
                    if qm > 0: sell_p += abs(qm) * price      # we sell what we bought
                    else: buy_p += abs(qm) * price
                if not good:
                    exit_val = val
                pnl = (exit_val - pos["cost0"]) * q
                n_orders = 2 * sum(abs(qm) for qm, _, _ in pos["legs"])
                cost = charges(pos["sell0"] + sell_p, pos["buy0"] + buy_p, n_orders) + SLIP * q * n_orders
                trades.append(dict(entry=pos["day"], exit=when, side=pos["side"], exp=pos["exp"], reason=reason,
                                   net=pnl - cost, gross=pnl, cost=cost))
                last_exit = (i, reason, pos["exp"])
                pos = None
                prev_b = b
                continue
        # -------- new entry decided at this close, executed at next open
        if pos is None and b != 0:
            if reentry == "fresh" and not (prev_b != b):
                prev_b = b; continue
            if last_exit and last_exit[0] == i:                # don't re-enter on the exit bar
                prev_b = b; continue
            ex_list = exps.get(nxt, [])
            exp = None
            if last_exit and last_exit[1] == "sl" and reentry in ("same", "fresh") and \
                    (last_exit[2] - nxt).days >= re_dte and last_exit[2] in ex_list:
                exp = last_exit[2]                               # re-enter on the same expiry
            if exp is None:
                cands = [e for e in ex_list if (e - nxt).days >= min_dte]
                exp = cands[0] if cands else None
            if exp is not None:
                S0 = d.Open.iloc[i + 1]
                atm = round(d.Close.iloc[i] / 50) * 50
                legs = [(qm, float(atm + off), kind) for qm, off, kind in legs_for(struct, b)]
                cost0 = 0.0; sell0 = buy0 = 0.0; good = True
                for qm, K, kind in legs:
                    p = px.get((nxt, exp, K, kind))
                    if p is None or p[2] < 50:
                        good = False; break
                    cost0 += qm * p[0]
                    if qm > 0: buy0 += qm * p[0]
                    else: sell0 += -qm * p[0]
                if good:
                    grid = np.arange(atm - 3000, atm + 3000, 25)
                    pay = np.array([expiry_payoff(legs, s) for s in grid]) - cost0
                    pos = dict(day=nxt, side=b, exp=exp, legs=legs, cost0=cost0, sell0=sell0, buy0=buy0,
                               S0=S0, maxp=float(pay.max()), maxl=float(pay.min()))
        prev_b = b
    return pd.DataFrame(trades)


def stats(t):
    if t.empty:
        return dict(n=0, net=0, pf=0, dd=0, win=0)
    eq = t.net.cumsum(); w = t.net[t.net > 0].sum(); l = -t.net[t.net <= 0].sum()
    return dict(n=len(t), net=round(t.net.sum()), pf=round(w / l, 2) if l > 0 else 9.99,
                dd=round(float((eq - eq.cummax().clip(lower=0)).min())), win=round(100 * (t.net > 0).mean(), 1))


_G = {}


def _init():
    d, px, exps = load()
    x = indicators(d)
    _G.update(d=d, px=px, exps=exps, x=x)


def job(args):
    bias_name, struct, sl, tgt, re, flip = args
    t = run(_G["d"], _G["x"], _G["px"], _G["exps"], bias_name, struct, sl, tgt, re, flip)
    if t.empty:
        return None
    tr, te = t[t.entry <= TRAIN_END], t[t.entry > TRAIN_END]
    yrs = t.groupby(t.entry.dt.year).net.sum().round().to_dict()
    return dict(bias=bias_name, struct=struct, sl=sl, tgt=tgt, reentry=re, flip=flip,
                **{f"tr_{k}": v for k, v in stats(tr).items()}, **{f"te_{k}": v for k, v in stats(te).items()},
                **{f"all_{k}": v for k, v in stats(t).items()}, **{f"y{k}": v for k, v in yrs.items()},
                sl_exits=int((t.reason == "sl").sum()))


def main():
    grid = list(itertools.product(BIASES, STRUCTS, (None, 0.01, 0.015, 0.02), (None, 0.5, 0.7),
                                  ("same", "fresh"), (False, True)))
    with Pool(4, initializer=_init) as pool:
        res = [r for r in pool.map(job, grid, chunksize=8) if r]
    g = pd.DataFrame(res)
    g.to_csv(OUT / "positional_grid.csv", index=False)
    print(len(g), "combinations")
    ok = (g.tr_n >= 25) & (g.y2022 > 0) & (g.y2023 > 0) & (g.y2024 > 0)
    c = g[ok].sort_values("tr_net", ascending=False)
    print(f"{len(c)} profitable in each of 2022-24; of those {int((c.te_net > 0).sum())} profitable in 2025-26")
    cols = ["bias", "struct", "sl", "tgt", "reentry", "flip", "tr_n", "tr_net", "tr_dd", "te_n", "te_net", "te_dd", "all_net", "all_pf", "all_win"]
    print(c.head(25)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
