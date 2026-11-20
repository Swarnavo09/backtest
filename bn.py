"""Bank Nifty backtests (monthly expiry only), reusing the Nifty engine.

  1. Directional intraday spread (Supertrend + EMA trigger, 30-min EMA filter, Linear Regression option)
  2. Non-directional intraday (straddle / strangle / iron butterfly / iron condor) on the monthly
  3. Positional trend debit spread on the monthly (real NSE premiums, EOD)

    SYM=BANKNIFTY NEXP=6 python fetch_bhav.py      -> data/banknifty_opt_bhav_6exp.csv.gz
    python bn.py                                    -> results/bn_*.csv / .json
"""
import bisect, itertools, json, sys
from dataclasses import replace
from datetime import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

import realiv
import run_ar_filters as AF
import run_exits as E
import run_v2 as R
import run_vwap as V
import strategy as S
from strategy import add_signals_v2, backtest

ROOT = Path(__file__).parent
LOT = 30
SPOT5 = ROOT / "data" / "banknifty_5m_5y.csv"
OPT = ROOT / "data" / "banknifty_opt_bhav_6exp.csv.gz"
_G = {}


def setup():
    S.LOT_SIZE = LOT
    S.STRIKE_STEP = 100
    realiv.OPT_FILE, realiv.SPOT_FILE = OPT, SPOT5
    rv = realiv.RealIV("mix70v")
    # monthly expiries = last expiry of each calendar month
    ex = pd.Series(rv.expiries)
    monthly = sorted(ex.groupby([ex.map(lambda d: d.year), ex.map(lambda d: d.month)]).max().tolist())
    rv.monthly = monthly

    def expiry_fn(ts, p):
        d = ts.date()
        k = bisect.bisect_left(monthly, d)
        return monthly[k] if k < len(monthly) else None          # trade the monthly, incl. on its expiry day

    S.PRICING.update(expiry=expiry_fn, iv=rv.iv_fn, price=rv.price_fn)
    b5 = S.load_bars(SPOT5, 5)
    full = b5.groupby(b5.index.date).size(); keep = set(full[full >= 70].index)
    b5 = b5[[d in keep for d in b5.index.date]]
    b15 = S.load_bars(SPOT5, 15); b15 = b15[[d in keep for d in b15.index.date]]
    vix = pd.read_csv(ROOT / "data" / "indiavix_1d_5y.csv", index_col=0, parse_dates=True)["Close"]
    vix.index = pd.to_datetime(vix.index).normalize()
    AF._b, AF._b5, AF._v = b15, b5, vix
    expday = np.array([d in set(monthly) for d in b15.index.date])
    # "expiry week" = the last 5 trading days up to and including the monthly expiry
    days = sorted(set(b15.index.date)); pos = {d: i for i, d in enumerate(days)}
    nextexp = {d: monthly[bisect.bisect_left(monthly, d)] if bisect.bisect_left(monthly, d) < len(monthly) else None for d in days}
    expweek = np.array([nextexp[d] is not None and nextexp[d] in pos and pos[nextexp[d]] - pos[d] <= 4 for d in b15.index.date])
    _G.update(rv=rv, b15=b15, vix=vix, expday=expday, expweek=expweek, monthly=monthly)


# ------------------------------------------------------------ 1. directional
def directional(args):
    hedge, sl_lot, linreg, days, sq, lots = args
    df = add_signals_v2(_G["b15"], "st_ema", "none", st=(10, 3.0))
    f = AF.filt("30m EMA 9/21", df); df["bull"] &= f[0]; df["bear"] &= f[1]
    if linreg:
        c = df.Close; xs = np.arange(20) - 9.5
        slope = c.rolling(20).apply(lambda y: (xs * (y - y.mean())).sum() / (xs ** 2).sum(), raw=True)
        df["bull"] &= (slope > 0).values; df["bear"] &= (slope < 0).values
    if days == "expiry week":
        df["bull"] &= _G["expweek"]; df["bear"] &= _G["expweek"]
    elif days == "expiry day":
        df["bull"] &= _G["expday"]; df["bear"] &= _G["expday"]
    el, es = E.exit_arrays(df, "30m EMA 9/21 flips")
    p = replace(R.mk(**{**V.BASE, "hedge": hedge}), max_trades=1, fresh=False, sl=1e6, lots=lots, dte0=True)
    tr = backtest(df, _G["vix"], p)
    r = E.simulate(df, tr, replace(p, squareoff=sq), el, es, sl_lot * lots)
    return dict(kind="directional", hedge=hedge, sl_lot=sl_lot, linreg=linreg, days=days, sq=sq.strftime("%H:%M"),
                lots=lots, **summ(r, "entry_ts"))


# --------------------------------------------------------- 2. non-directional
NONDIR = {"short straddle": [(-1, 0, "C"), (-1, 0, "P")],
          "short strangle 500": [(-1, 500, "C"), (-1, -500, "P")],
          "iron butterfly 1000": [(-1, 0, "C"), (-1, 0, "P"), (+1, 1000, "C"), (+1, -1000, "P")],
          "iron condor 500/1200": [(-1, 500, "C"), (-1, -500, "P"), (+1, 1200, "C"), (+1, -1200, "P")]}


def nondir(args):
    struct, et, ext, sl, tg, days, lots = args
    rv, bars = _G["rv"], _G["b15"]
    q = LOT * lots
    rows = []
    for day, g in bars.groupby(bars.index.date):
        if days == "expiry day" and day not in set(_G["monthly"]): continue
        if days == "expiry week" and not _G["expweek"][bars.index.date == day][0]: continue
        g = g[g.index.time >= et]
        if g.empty: continue
        t0 = g.index[0]
        exp = S.PRICING["expiry"](t0, None)
        i = rv.day_pos.get(day)
        if exp is None or not i: continue
        prev = rv.days[i - 1]
        s0 = g.Open.iloc[0]; atm = round(s0 / 100) * 100
        legs = [(qq, atm + off, k) for qq, off, k in NONDIR[struct]]
        ivs = [rv.leg_iv(prev, exp, K, k) for _, K, k in legs]
        if any(v is None for v in ivs): continue

        def val(spot, ts):
            tt = ts.tz_localize(None).to_pydatetime(); T = rv.T(tt, exp); kv = rv.vix_ratio(tt)
            return sum(qq * S.bs_price(spot, K, T, iv * kv, k) for (qq, K, k), iv in zip(legs, ivs))

        v0 = val(s0, t0); credit = -v0
        cap = credit * q; pnl = None; reason = "time"
        for ts, b in g.iterrows():
            if ts.time() >= ext:
                pnl = (val(b.Open, ts) - v0) * q; break
            mo = (val(b.Open, ts) - v0) * q
            mh, ml = (val(b.High, ts) - v0) * q, (val(b.Low, ts) - v0) * q
            worst, best = min(mh, ml), max(mh, ml)
            if sl and mo <= -sl * cap: pnl, reason = mo, "sl"; break
            if tg and mo >= tg * cap: pnl, reason = mo, "target"; break
            if sl and worst <= -sl * cap: pnl, reason = -sl * cap, "sl"; break
            if tg and best >= tg * cap: pnl, reason = tg * cap, "target"; break
        if pnl is None: continue
        prem = sum(abs(S.bs_price(s0, K, rv.T(t0.tz_localize(None).to_pydatetime(), exp), iv, k)) for (_, K, k), iv in zip(legs, ivs))
        cost = S.charges(prem, prem, lots) * (len(legs) / 2) + 0.5 * 2 * q * len(legs) * 2 / 2
        rows.append(dict(entry_ts=t0, net=pnl - cost, reason=reason))
    r = pd.DataFrame(rows)
    if not r.empty:
        r["net_1lot"] = r.net / lots
    return dict(kind="nondir", struct=struct, entry=et.strftime("%H:%M"), exit=ext.strftime("%H:%M"), sl=sl, tgt=tg,
                days=days, lots=lots, **summ(r, "entry_ts"))


def summ(r, col):
    if r.empty:
        return dict(train=R.stats(r), test=R.stats(r), all=R.stats(r), years={}, last12=0)
    d = r[col].dt.strftime("%Y-%m-%d")
    m = r.groupby(r[col].dt.strftime("%Y-%m")).net.sum()
    return dict(train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                years={int(k): round(v) for k, v in r.groupby(r[col].dt.year).net.sum().items()},
                last12=round(m.iloc[-12:].sum()))


def flat(res):
    out = []
    for r in res:
        row = {k: v for k, v in r.items() if k not in ("train", "test", "all", "years")}
        row.update(train=r["train"]["net"], tr_dd=r["train"]["dd"], test=r["test"]["net"], all=r["all"]["net"],
                   dd=r["all"]["dd"], pf=r["all"]["pf"], win=r["all"]["win"], n=r["all"]["n"],
                   neg=sum(v < 0 for v in r["years"].values()), years=r["years"])
        out.append(row)
    return pd.DataFrame(out)


def main():
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 90)
    jobs_d = list(itertools.product((500, 700, 1000), (1500, 2500, 3500), (False, True),
                                    ("all days", "expiry week", "expiry day"), (time(15, 0),), (2,)))
    jobs_n = list(itertools.product(NONDIR, (time(9, 30), time(10, 30), time(12, 0)), (time(15, 0),), (0.3, 0.5, None),
                                    (None,), ("all days", "expiry week", "expiry day"), (2,)))
    with Pool(4, initializer=setup) as pool:
        rd = pool.map(directional, jobs_d)
        rn = pool.map(nondir, jobs_n, chunksize=2)
    gd, gn = flat(rd), flat(rn)
    gd.to_csv(R.OUT / "bn_directional.csv", index=False); gn.to_csv(R.OUT / "bn_nondir.csv", index=False)
    for name, g in (("DIRECTIONAL intraday spread", gd), ("NON-DIRECTIONAL intraday", gn)):
        g["score"] = g.train / (1 + g.tr_dd.abs() / 30000)
        print(f"\n===== {name} (2 lots, monthly expiry) — top 12 by 2022-24 score")
        print(g.sort_values("score", ascending=False).head(12).drop(columns=["score"]).to_string(index=False))


if __name__ == "__main__":
    main()
