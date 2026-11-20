"""Second exit layer on the current strategy (Mon/Tue/Thu, 30m EMA filter, 30m EMA flip exit, Rs 3,000/lot stop, 15:00).

A candidate exit fires at a 15-minute candle close (fill at the next candle's open), optionally only while the
trade is in profit by at least a gate (Rs per lot).

    python run_exit2.py   -> results/exit2.json, results/exit2_grid.csv
"""
import json
from dataclasses import replace
from datetime import time
import numpy as np, pandas as pd
import run_ar_filters as AF, run_exits as E, run_filters3 as F3, run_tune as U, run_v2 as R, run_vwap as V
import strategy as S
from strategy import ema, supertrend, backtest

U._init(); F3.build()
F = F3.F
base = U._G["base"].copy()
ok = ~np.isin(base.index.weekday, [2, 4, 5, 6])                 # Mon, Tue, Thu only
base["bull"] &= ok; base["bear"] &= ok
df = base
c, o, h, l = df.Close, df.Open, df.High, df.Low
el0, es0 = E.exit_arrays(df, "30m EMA 9/21 flips")              # existing exit layer

# 30-minute close vs 30-minute EMA9
b5 = AF._b5
m30 = b5.resample("30min", offset="15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
cts = [min(t + pd.Timedelta(minutes=30), t.normalize() + pd.Timedelta(hours=15, minutes=30)) for t in m30.index]
sc = df.index + pd.Timedelta(minutes=15)
def on15(series):
    s = pd.Series(np.asarray(series, float), index=pd.DatetimeIndex(cts)); s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(sc)).ffill().reindex(sc).values
d30_c9 = on15(m30.Close - ema(m30.Close, 9))
d30_c21 = on15(m30.Close - ema(m30.Close, 21))
stf, _ = supertrend(df, 7, 2.0)
hist = (df.macd - df.sig)

EX = {   # name -> (exit for BULL trade, exit for BEAR trade)
    "15m EMA9 crosses below/above EMA21": (df.ema_f < df.ema_s, df.ema_f > df.ema_s),
    "15m close below/above EMA9": (c < df.ema_f, c > df.ema_f),
    "15m close below/above EMA21": (c < df.ema_s, c > df.ema_s),
    "15m Supertrend(10,3) flips": (df.st_dir == -1, df.st_dir == 1),
    "15m Supertrend(7,2) flips (faster)": (stf == -1, stf == 1),
    "Red/green candle against you": (c < o, c > o),
    "Two candles against you in a row": ((c < o) & (c.shift() < o.shift()), (c > o) & (c.shift() > o.shift())),
    "Close breaks previous candle low/high": (c < l.shift(), c > h.shift()),
    "30m close below/above 30m EMA9": (d30_c9 < 0, d30_c9 > 0),
    "30m close below/above 30m EMA21": (d30_c21 < 0, d30_c21 > 0),
    "MACD crosses signal": (F["MACD > signal"][1], F["MACD > signal"][0]),
    "MACD histogram falling 2 candles": ((hist < hist.shift()) & (hist.shift() < hist.shift(2)), (hist > hist.shift()) & (hist.shift() > hist.shift(2))),
    "Parabolic SAR flips": (F["Parabolic SAR"][1], F["Parabolic SAR"][0]),
    "RSI below/above 50": (F["RSI>50 / <50"][1], F["RSI>50 / <50"][0]),
    "Stochastic below/above 50": (F["Stochastic %K>50 / <50"][1], F["Stochastic %K>50 / <50"][0]),
    "Bollinger middle band break": (F["Bollinger: above/below middle"][1], F["Bollinger: above/below middle"][0]),
    "Linear regression slope turns": (F["Linear regression slope (20)"][1], F["Linear regression slope (20)"][0]),
    "Close below/above TEMA(20)": (F["Close vs TEMA(20)"][1], F["Close vs TEMA(20)"][0]),
}
EX = {k: (np.nan_to_num(np.asarray(a, float)) > 0, np.nan_to_num(np.asarray(b, float)) > 0) for k, (a, b) in EX.items()}


def simulate(tr, p, lots, ex2, gate_per_lot, loss_per_lot=3000):
    q = S.LOT_SIZE * lots; loss = loss_per_lot * lots
    idx = df.index; pos = {t: i for i, t in enumerate(idx)}
    O, H, L, C = o.values, h.values, l.values, c.values
    gate = None if gate_per_lot is None else gate_per_lot * lots
    out = []
    for t in tr.itertuples():
        side = 1 if t.side == "BULL PUT" else -1
        kind = "P" if side == 1 else "C"
        legs = ((t.short_strike, kind), (t.hedge_strike, kind))
        exp = S.PRICING["expiry"](t.entry_ts, p)
        ivs = tuple(float(x) for x in t.iv.strip("()").split(","))
        val = lambda spot, ts: S.PRICING["price"](spot, ts, legs, exp, ivs)
        mtm = lambda sv: (t.credit - (sv[0] - sv[1])) * q
        e1 = el0 if side == 1 else es0
        e2 = None if ex2 is None else (ex2[0] if side == 1 else ex2[1])
        i = pos[t.entry_ts]; reason = "time"; exit_v = None
        while i < len(idx):
            ts = idx[i]
            if ts.time() >= p.squareoff or ts.date() != t.entry_ts.date():
                exit_v = val(O[i], ts); break
            worst = L[i] if side == 1 else H[i]
            if mtm(val(O[i], ts)) <= -loss: exit_v, reason = val(O[i], ts), "sl"; break
            if mtm(val(worst, ts)) <= -loss: exit_v, reason = (t.credit + loss / q, 0.0), "sl"; break
            nxt_ok = i + 1 < len(idx) and idx[i + 1].date() == ts.date()
            if e1[i] and nxt_ok:
                exit_v, reason = val(O[i + 1], idx[i + 1]), "ema30_flip"; break
            if e2 is not None and e2[i] and nxt_ok:
                if gate is None or mtm(val(C[i], ts + pd.Timedelta(minutes=15))) >= gate:
                    exit_v, reason = val(O[i + 1], idx[i + 1]), "exit2"; break
            i += 1
        if exit_v is None: exit_v = val(C[i - 1], idx[i - 1])
        cc = exit_v[0] - exit_v[1]
        s_in, l_in = val(t.spot_in, t.entry_ts)
        s_out, l_out = exit_v if exit_v[1] > 0 else (cc + l_in, l_in)
        net = (t.credit - cc) * q - S.charges(s_in + l_out, l_in + s_out, lots) - 4 * p.slip * q
        out.append(dict(entry_ts=t.entry_ts, net=net, reason=reason))
    r = pd.DataFrame(out); r["net_1lot"] = r.net / lots
    return r


def summ(r):
    r = r.sort_values("entry_ts"); d = r.entry_ts.dt.strftime("%Y-%m-%d")
    eq = r.net.cumsum(); dd = (eq - eq.cummax().clip(lower=0)).min()
    w, lo = r.net[r.net > 0], r.net[r.net <= 0]
    return dict(trades=len(r), win=round(100 * (r.net > 0).mean(), 1), pf=round(w.sum() / -lo.sum(), 2),
                train=round(r[d <= R.TRAIN_END].net.sum()), test=round(r[d > R.TRAIN_END].net.sum()), total=round(r.net.sum()),
                dd=round(dd), since_sep25=round(r[d >= "2025-09-01"].net.sum()), before_sep25=round(r[d < "2025-09-01"].net.sum()),
                years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                neg_years=int((r.groupby(r.entry_ts.dt.year).net.sum() < 0).sum()),
                n_exit2=int((r.reason == "exit2").sum()), n_sl=int((r.reason == "sl").sum()),
                exit2_avg=round(r[r.reason == "exit2"].net.mean()) if (r.reason == "exit2").any() else 0)


if __name__ == "__main__":
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, lots=6, squareoff=time(15, 0))
    tr6 = backtest(df, AF._v, p)
    rows = []
    b = summ(simulate(tr6, p, 6, None, None)); rows.append(dict(exit2="NONE (current)", gate="-", **b))
    print("BASELINE 6 lots:", {k: b[k] for k in ("trades", "win", "pf", "train", "test", "total", "dd", "neg_years")})
    for name, ex2 in EX.items():
        for gname, gate in (("any time", None), ("only in profit", 0), ("profit >= Rs1,000/lot", 1000), ("profit >= Rs2,000/lot", 2000)):
            rows.append(dict(exit2=name, gate=gname, **summ(simulate(tr6, p, 6, ex2, gate))))
    g = pd.DataFrame(rows); g.to_csv(R.OUT / "exit2_grid.csv", index=False)
    json.dump(rows, open(R.OUT / "exit2.json", "w"), indent=1, default=str)
    pd.set_option("display.width", 270); pd.set_option("display.max_colwidth", 44)
    cols = ["exit2", "gate", "trades", "win", "pf", "train", "test", "total", "dd", "since_sep25", "neg_years", "n_exit2", "exit2_avg"]
    print(g[cols].sort_values("train", ascending=False).head(25).to_string(index=False))
    print("\nbest total:"); print(g[cols].sort_values("total", ascending=False).head(8).to_string(index=False))
