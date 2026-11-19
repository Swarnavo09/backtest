"""AlgoRooms-style profit protection on overall MTM (rupees), 6 lots.

Modes (as in AlgoRooms Risk Management):
  none        : exit at -LOSS or 14:45
  lock        : once MTM peak >= X, stop moves to +Y (Lock Fix Profit)
  trail       : for every X of MTM peak, stop rises by Y (Trail Profit)
  lock_trail  : once peak >= X stop = +Y, then every A more, stop += B (Lock and Trail)

Each 15-minute candle: the stop is checked at the candle's worst Nifty price; the MTM
peak is updated with its best price and the new stop applies from the next candle.

    python run_trailing.py   -> results/trailing.json
"""
import itertools
import json
import math
from dataclasses import replace
from multiprocessing import Pool

import numpy as np
import pandas as pd

import realiv
import run_ar_filters as AF
import run_v2 as R
import run_vwap as V
import strategy as S
from strategy import add_signals_v2, backtest

LOSS = 18000
FILTERS = ["30m EMA 9/21", "ADX 20", "EMA 50/200 trend"]
_rv = None


def _init():
    global _rv
    AF._init()
    _rv = realiv.install("mix70v")


def entries(fname):
    df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
    f = AF.filt(fname, df)
    df["bull"] &= f[0]
    df["bear"] &= f[1]
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0)   # entries only; exits simulated below
    tr = backtest(df, AF._v, p)
    return df, tr, p


def simulate(df, tr, p, mode, prm):
    q = S.LOT_SIZE * p.lots
    idx = df.index
    pos = {t: i for i, t in enumerate(idx)}
    out = []
    for t in tr.itertuples():
        side = 1 if t.side == "BULL PUT" else -1
        kind = "P" if side == 1 else "C"
        legs = ((t.short_strike, kind), (t.hedge_strike, kind))
        exp = S.PRICING["expiry"](t.entry_ts, p)
        ivs = tuple(float(x) for x in t.iv.strip("()").split(","))
        credit = t.credit
        val = lambda spot, ts: S.PRICING["price"](spot, ts, legs, exp, ivs)
        mtm = lambda sv: (credit - (sv[0] - sv[1])) * q
        stop, peak = -LOSS, 0.0
        i = pos[t.entry_ts]
        exit_px = exit_ts = None
        reason = "time"
        while i < len(idx):
            ts = idx[i]
            if ts.time() >= p.squareoff or ts.date() != t.entry_ts.date():
                exit_ts, exit_v = ts, val(df.Open.iloc[i], ts)
                break
            o, h, l, c = df.Open.iloc[i], df.High.iloc[i], df.Low.iloc[i], df.Close.iloc[i]
            worst, best = (l, h) if side == 1 else (h, l)
            m_open = mtm(val(o, ts))
            if m_open <= stop:                                   # gapped through the stop
                exit_ts, exit_v, reason = ts, val(o, ts), "sl" if stop < 0 else "lock"
                break
            if mtm(val(worst, ts)) <= stop:                      # stop hit inside the candle
                exit_ts, reason = ts, "sl" if stop < 0 else "lock"
                exit_v = (credit - stop / q, 0.0)                # fill at the stop level
                break
            peak = max(peak, mtm(val(best, ts)))
            if mode == "lock" and peak >= prm["X"]:
                stop = max(stop, prm["Y"])
            elif mode == "trail" and peak > 0:
                stop = max(stop, -LOSS + math.floor(peak / prm["X"]) * prm["Y"])
            elif mode == "lock_trail" and peak >= prm["X"]:
                stop = max(stop, prm["Y"] + math.floor((peak - prm["X"]) / prm["A"]) * prm["B"])
            i += 1
        if exit_ts is None:
            exit_ts, exit_v = idx[i - 1], val(df.Close.iloc[i - 1], idx[i - 1])
        close_cost = exit_v[0] - exit_v[1]
        gross = (credit - close_cost) * q
        s_in, l_in = val(t.spot_in, t.entry_ts)
        s_out, l_out = (exit_v if exit_v[1] > 0 else (close_cost + l_in, l_in))   # stop fills: hedge ~ unchanged
        cost = S.charges(s_in + l_out, l_in + s_out, p.lots) + 4 * p.slip * q
        out.append(dict(entry_ts=t.entry_ts, net=gross - cost, reason=reason))
    r = pd.DataFrame(out)
    r["net_1lot"] = r.net / p.lots
    return r


PARAMS = {
    "none": [{}],
    "lock": [dict(X=x, Y=y) for x, y in itertools.product((6000, 9000, 12000, 18000, 24000), (0, 3000, 6000, 9000, 12000)) if y < x],
    "trail": [dict(X=x, Y=y) for x, y in ((3000, 3000), (6000, 6000), (9000, 9000), (6000, 3000), (12000, 6000), (12000, 12000), (18000, 9000))],
    "lock_trail": [dict(X=x, Y=y, A=a, B=b) for x, y, a, b in itertools.product((9000, 12000, 18000), (0, 3000, 6000), (3000, 6000), (3000,)) if y < x],
}


def job(fname):
    df, tr, p = entries(fname)
    rows = []
    for mode, plist in PARAMS.items():
        for prm in plist:
            r = simulate(df, tr, p, mode, prm)
            d = r.entry_ts.dt.strftime("%Y-%m-%d")
            yrs = r.groupby(r.entry_ts.dt.year).net.sum().round().to_dict()
            rows.append(dict(filter=fname, mode=mode, **{k: v for k, v in prm.items()},
                             train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                             years={int(k): v for k, v in yrs.items()}, reasons=r.reason.value_counts().to_dict()))
    return rows


def main():
    with Pool(3, initializer=_init) as pool:
        res = [x for chunk in pool.map(job, FILTERS) for x in chunk]
    (R.OUT / "trailing.json").write_text(json.dumps(res, indent=1, default=str))
    df = pd.DataFrame([{**{k: r[k] for k in ("filter", "mode")}, "prm": {k: r.get(k) for k in ("X", "Y", "A", "B") if r.get(k) is not None},
                        "train": r["train"]["net"], "test": r["test"]["net"], "all": r["all"]["net"], "dd": r["all"]["dd"],
                        "pf_test": r["test"]["pf"], "neg_years": sum(v < 0 for v in r["years"].values())} for r in res])
    for f in FILTERS:
        g = df[df["filter"] == f]
        print(f"\n=== {f}")
        for mode in PARAMS:
            gm = g[g["mode"] == mode].sort_values("train", ascending=False)
            print(f"  {mode:10} best-on-train: {gm.iloc[0].to_dict()}")
            print(f"  {'':10} median test {gm.test.median():.0f}, share of settings beating no-trailing test: "
                  f"{(gm.test > g[g['mode']=='none'].test.iloc[0]).mean():.0%}")


if __name__ == "__main__":
    main()
