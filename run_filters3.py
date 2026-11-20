"""Extra AlgoRooms-indicator filters (and an option-volume proxy) on the intraday spread.

    python run_filters3.py   -> results/filters3.json, results/filters3_grid.csv
"""
import itertools, json
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import run_tune as U
import run_v2 as R
from strategy import ema, macd

F = {}


def build():
    df = U._G["base"]
    c, h, l = df.Close, df.High, df.Low
    n = len(df)
    a, p, m = U._G["adx"], U._G["pdi"], U._G["ndi"]
    for th in (15, 20, 25, 30):
        F[f"ADX>{th} +DI/-DI"] = ((a > th) & (p > m), (a > th) & (m > p))
        F[f"ADX>{th}"] = (a > th, a > th)
    F["ADX<25 (no strong trend)"] = (a < 25, a < 25)
    F["+DI>-DI only"] = (p > m, m > p)
    r = U._G["rsi"]
    F["RSI>50 / <50"] = (r > 50, r < 50)
    F["RSI 50-70 / 30-50"] = ((r > 50) & (r < 70), (r > 30) & (r < 50))
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    k = 100 * (c - lo14) / (hi14 - lo14); dk = k.rolling(3).mean()
    F["Stochastic %K>50 / <50"] = ((dk > 50).values, (dk < 50).values)
    F["Stochastic not extreme (20-80)"] = (((dk > 20) & (dk < 80)).values,) * 2
    mid = c.rolling(20).mean(); sd = c.rolling(20).std()
    up, bot = mid + 2 * sd, mid - 2 * sd
    F["Bollinger: above/below middle"] = ((c > mid).values, (c < mid).values)
    F["Bollinger: inside bands"] = (((c < up) & (c > mid)).values, ((c > bot) & (c < mid)).values)
    F["Bollinger: band width > 20-bar avg"] = (((up - bot) > (up - bot).rolling(20).mean()).values,) * 2
    # Parabolic SAR (0.02, 0.2)
    sar = np.zeros(n); trend = np.ones(n, int); af = 0.02; ep = h.iloc[0]; sar[0] = l.iloc[0]
    H, L = h.values, l.values
    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1]); trend[i] = trend[i - 1]
        if trend[i] == 1:
            if L[i] < sar[i]: trend[i] = -1; sar[i] = ep; ep = L[i]; af = 0.02
            elif H[i] > ep: ep = H[i]; af = min(af + 0.02, 0.2)
        else:
            if H[i] > sar[i]: trend[i] = 1; sar[i] = ep; ep = H[i]; af = 0.02
            elif L[i] < ep: ep = L[i]; af = min(af + 0.02, 0.2)
    F["Parabolic SAR"] = (trend == 1, trend == -1)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    F["ATR(14) > 20-bar avg (vol rising)"] = ((atr > atr.rolling(20).mean()).values,) * 2
    F["ATR(14) < 20-bar avg (vol calm)"] = ((atr < atr.rolling(20).mean()).values,) * 2
    F["True Range < 1.5x ATR (no spike candle)"] = ((tr < 1.5 * atr).values,) * 2
    e1 = ema(c, 20); e2 = ema(e1, 20); e3 = ema(e2, 20); tema = 3 * e1 - 3 * e2 + e3
    F["Close vs TEMA(20)"] = ((c > tema).values, (c < tema).values)
    w = np.arange(1, 21); wma = c.rolling(20).apply(lambda x: (x * w).sum() / w.sum(), raw=True)
    F["Close vs WMA(20)"] = ((c > wma).values, (c < wma).values)
    xs = np.arange(20); xs = xs - xs.mean()
    slope = c.rolling(20).apply(lambda y: (xs * (y - y.mean())).sum() / (xs ** 2).sum(), raw=True)
    F["Linear regression slope (20)"] = ((slope > 0).values, (slope < 0).values)
    ml, sg = macd(c)
    F["MACD > signal"] = ((ml > sg).values, (ml < sg).values)
    F["MACD > 0"] = ((ml > 0).values, (ml < 0).values)
    # daily pivot / camarilla from previous day
    day = pd.Series(df.index.date, index=df.index)
    d = df.groupby(day).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last")).shift(1)
    P = day.map((d.h + d.l + d.c) / 3).values
    rng = day.map(d.h - d.l).values; pc = day.map(d.c).values
    H3, L3 = pc + rng * 1.1 / 4, pc - rng * 1.1 / 4
    F["Pivot point"] = (c.values > P, c.values < P)
    F["Camarilla: between L3 and H3 (range day)"] = (((c.values < H3) & (c.values > L3)),) * 2
    F["Camarilla: breakout beyond H3/L3"] = (c.values > H3, c.values < L3)
    # option-volume proxy: yesterday's ATM CE+PE volume (nearest expiry) vs its 20-day average
    o = pd.read_csv(R.ROOT / "data" / "nifty_opt_bhav_4exp.csv.gz", parse_dates=["date", "expiry"],
                    usecols=["date", "expiry", "strike", "type", "close", "volume", "under"])
    dc = df.groupby(day).Close.last()
    vols = {}
    for dt, g in o.groupby("date"):
        dd = dt.date()
        if dd not in dc.index: continue
        e0 = g.expiry.min(); atm = round(dc[dd] / 50) * 50
        vols[dd] = g[(g.expiry == e0) & (g.strike.between(atm - 100, atm + 100))].volume.sum()
    v = pd.Series(vols).sort_index()
    ratio = (v / v.rolling(20).mean()).shift(1)          # known before the day starts
    rr = day.map(ratio).values
    F["Option volume yesterday > 20d avg"] = ((rr > 1),) * 2
    F["Option volume yesterday < 20d avg"] = ((rr < 1),) * 2
    F["Option volume yesterday > 1.3x avg"] = ((rr > 1.3),) * 2
    for kk, vv in list(F.items()):
        F[kk] = (np.nan_to_num(np.asarray(vv[0], float)) > 0, np.nan_to_num(np.asarray(vv[1], float)) > 0)


def _init():
    U._init(); build()
    import run_tune2 as T2
    F["__exp"] = T2.daymask("expiry day only")


def run(names, expiry_only, lots=6):
    df0 = U._G["base"]; df = df0.copy()
    for nm in names:
        b, s = F[nm]; df["bull"] &= b; df["bear"] &= s
    if expiry_only:
        df["bull"] &= F["__exp"]; df["bear"] &= F["__exp"]
    U._G["base"] = df
    try:
        r = U.simulate("none", time(9, 30), time(13, 30), None, lots)
    finally:
        U._G["base"] = df0
    return r


def job(args):
    names, exp_only = args
    s = U.summ(run(names, exp_only))
    return dict(filters=" + ".join(names) if names else "none", expiry_only=exp_only, **s)


def flat(res):
    return pd.DataFrame([dict(filters=r["filters"], expiry_only=r["expiry_only"], train=r["train"]["net"], tr_dd=r["train"]["dd"],
                              test=r["test"]["net"], te_dd=r["test"]["dd"], all=r["all"]["net"], dd=r["all"]["dd"],
                              pf=r["all"]["pf"], win=r["all"]["win"], trades=r["all"]["n"],
                              neg=sum(v < 0 for v in r["years"].values())) for r in res])


def main():
    with Pool(4, initializer=_init) as pool:
        names = pool.apply(lambda: None) if False else None
        _init_local = _init; _init_local()
        single = [k for k in F if not k.startswith("__")]
        res1 = pool.map(job, [([], e) for e in (False, True)] + [([k], e) for k in single for e in (False, True)])
        g1 = flat(res1)
        g1["score"] = g1.train / (1 + g1.tr_dd.abs() / 50000)       # 2022-24 only
        # combine: top 6 single filters per base (by train score, must beat base on train score) -> all pairs and triples
        combos = []
        for e in (False, True):
            gg = g1[g1.expiry_only == e]
            base_score = gg[gg.filters == "none"].score.iloc[0]
            top = [f for f in gg.sort_values("score", ascending=False).filters if f != "none"][:6]
            top = [f for f in top if gg[gg.filters == f].score.iloc[0] > base_score * 0.95] or top[:3]
            for kk in (2, 3):
                combos += [(list(c), e) for c in itertools.combinations(top, kk)]
        res2 = pool.map(job, combos)
    g2 = flat(res2); g2["score"] = g2.train / (1 + g2.tr_dd.abs() / 50000)
    g = pd.concat([g1, g2], ignore_index=True)
    g.to_csv(R.OUT / "filters3_grid.csv", index=False)
    (R.OUT / "filters3.json").write_text(json.dumps(res1 + res2, indent=1, default=str))
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
    for e in (False, True):
        print(f"\n===== base: {'EXPIRY DAY ONLY' if e else 'ALL DAYS'} (6 lots) =====")
        gg = g[g.expiry_only == e]
        print(gg[gg.filters == "none"].drop(columns=["score"]).to_string(index=False))
        print("single filters, ranked by 2022-24 score:")
        print(g1[g1.expiry_only == e].sort_values("score", ascending=False).drop(columns=["expiry_only", "score"]).to_string(index=False))
        print("best combinations (by 2022-24 score):")
        print(g2[g2.expiry_only == e].sort_values("score", ascending=False).head(10).drop(columns=["expiry_only", "score"]).to_string(index=False))


if __name__ == "__main__":
    main()
