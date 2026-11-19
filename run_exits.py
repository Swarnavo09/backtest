"""Exit rules besides the 14:45 square-off, at 4 and 6 lots (loss limit Rs 3,000/lot).

    python run_exits.py   -> results/exits.json
"""
import json
import math
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import run_ar_filters as AF
import run_trailing as T
import run_v2 as R
import strategy as S
from strategy import ema, macd


def exit_arrays(df, name):
    c = df.Close
    if name == "none":
        z = np.zeros(len(df), bool); return z, z
    if name == "Supertrend flips":
        return (df.st_dir == -1).values, (df.st_dir == 1).values
    if name == "Close crosses EMA 21":
        return (c < df.ema_s).values, (c > df.ema_s).values
    if name == "EMA 9 crosses EMA 21":
        return (df.ema_f < df.ema_s).values, (df.ema_f > df.ema_s).values
    if name == "MACD crosses signal":
        return (df.macd < df.sig).values, (df.macd > df.sig).values
    if name == "Close crosses EMA 9":
        return (c < df.ema_f).values, (c > df.ema_f).values
    if name == "30m EMA 9/21 flips":
        d = AF.htf(30, "ema"); return d < 0, d > 0
    if name == "1H Supertrend flips":
        d = AF.htf(60, "st"); return d < 0, d > 0
    raise ValueError(name)


def simulate(df, tr, p, ex_long, ex_short, loss, target=None):
    q = S.LOT_SIZE * p.lots
    idx = df.index
    pos = {t: i for i, t in enumerate(idx)}
    O, H, L, C = df.Open.values, df.High.values, df.Low.values, df.Close.values
    out = []
    for t in tr.itertuples():
        side = 1 if t.side == "BULL PUT" else -1
        kind = "P" if side == 1 else "C"
        legs = ((t.short_strike, kind), (t.hedge_strike, kind))
        exp = S.PRICING["expiry"](t.entry_ts, p)
        ivs = tuple(float(x) for x in t.iv.strip("()").split(","))
        val = lambda spot, ts: S.PRICING["price"](spot, ts, legs, exp, ivs)
        mtm = lambda sv: (t.credit - (sv[0] - sv[1])) * q
        exc = ex_long if side == 1 else ex_short
        i = pos[t.entry_ts]; reason = "time"; exit_v = None
        while i < len(idx):
            ts = idx[i]
            if ts.time() >= p.squareoff or ts.date() != t.entry_ts.date():
                exit_v = val(O[i], ts); break
            worst = L[i] if side == 1 else H[i]
            if mtm(val(O[i], ts)) <= -loss:
                exit_v, reason = val(O[i], ts), "sl"; break
            if mtm(val(worst, ts)) <= -loss:
                exit_v, reason = (t.credit + loss / q, 0.0), "sl"; break
            if target is not None:
                best = H[i] if side == 1 else L[i]
                if mtm(val(O[i], ts)) >= target:
                    exit_v, reason = val(O[i], ts), "target"; break
                if mtm(val(best, ts)) >= target:
                    exit_v, reason = (t.credit - target / q, 0.0), "target"; break
            if exc[i] and i + 1 < len(idx) and idx[i + 1].date() == ts.date():   # signal at close -> exit next open
                exit_v, reason = val(O[i + 1], idx[i + 1]), "exit_rule"; break
            i += 1
        if exit_v is None:
            exit_v = val(C[i - 1], idx[i - 1])
        cc = exit_v[0] - exit_v[1]
        s_in, l_in = val(t.spot_in, t.entry_ts)
        s_out, l_out = exit_v if exit_v[1] > 0 else (cc + l_in, l_in)
        net = (t.credit - cc) * q - S.charges(s_in + l_out, l_in + s_out, p.lots) - 4 * p.slip * q
        out.append(dict(entry_ts=t.entry_ts, net=net, reason=reason))
    r = pd.DataFrame(out); r["net_1lot"] = r.net / p.lots
    return r


EXITS = ["none", "Supertrend flips", "Close crosses EMA 21", "EMA 9 crosses EMA 21", "MACD crosses signal",
         "Close crosses EMA 9", "30m EMA 9/21 flips", "1H Supertrend flips"]
TIMES = [time(14, 0), time(14, 15), time(14, 30), time(14, 45), time(15, 0), time(15, 10)]


def job(args):
    lots = args
    T._init()
    df, tr, p = T.entries("30m EMA 9/21")
    rows = []
    for sq in TIMES:
        # entries are the same for every square-off time (signals stop at 13:30)
        for ex in EXITS:
            el, es = exit_arrays(df, ex)
            pp = replace(p, lots=lots, squareoff=sq)
            r = simulate(df, tr, pp, el, es, 3000 * lots)
            d = r.entry_ts.dt.strftime("%Y-%m-%d")
            rows.append(dict(lots=lots, squareoff=sq.strftime("%H:%M"), exit=ex,
                             train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                             years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                             reasons=r.reason.value_counts().to_dict()))
    return rows


def main():
    with Pool(2) as pool:
        res = [x for c in pool.map(job, [4, 6]) for x in c]
    (R.OUT / "exits.json").write_text(json.dumps(res, indent=1, default=str))
    df = pd.DataFrame([dict(lots=r["lots"], sq=r["squareoff"], exit=r["exit"], train=r["train"]["net"], test=r["test"]["net"],
                            all=r["all"]["net"], dd=r["all"]["dd"], pf=r["all"]["pf"],
                            neg=sum(v < 0 for v in r["years"].values()), yrs=r["years"]) for r in res])
    for lots in (4, 6):
        g = df[df.lots == lots]
        base = g[(g.sq == "14:45") & (g.exit == "none")].iloc[0]
        print(f"\n=== {lots} lots  baseline 14:45 only: all {base['all']} train {base.train} test {base.test} dd {base.dd}")
        better = g[(g["all"] > base["all"]) & (g.train > base.train * 0.95) & (g.test > base.test * 0.95)].sort_values("all", ascending=False)
        print(better.drop(columns="lots").to_string(index=False))
        print("\nall settings ranked:")
        print(g.sort_values("all", ascending=False).head(12).drop(columns=["lots", "yrs"]).to_string(index=False))


if __name__ == "__main__":
    main()
