"""
Nifty Futures intraday backtest of the "NIFTY SPREAD" indicator conditions
(SuperTrend 10,3 + EMA9/EMA21 + higher-TF EMA9/EMA21), with optional
Volume and VWAP filters, fixed stop loss and fixed R:R target.

Data limits (free Yahoo feed):
  * 2+ years of history only at 60-minute bars (15m only covers ~60 days).
  * Nifty index has no volume -> volume proxy = rupee turnover of the 15
    heaviest Nifty stocks (they drive futures volume). The 09:15 bar volume
    is missing in Yahoo, so it is rebuilt as daily volume minus other bars.
  * Spot price used as the futures price (intraday moves are ~identical;
    basis does not affect intraday P&L).
"""
import itertools, sys
import numpy as np, pandas as pd

LOT = 65
STOCKS = ["RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","BHARTIARTL.NS","TCS.NS",
          "LT.NS","ITC.NS","SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","M&M.NS","BAJFINANCE.NS",
          "HINDUNILVR.NS","SUNPHARMA.NS"]


def cost_points(price, stt=0.0002):
    """Round-trip cost for 1 lot in index points: brokerage 40, STT on sell side,
    exchange+SEBI+stamp+GST (~0.0045% of turnover) and 1 pt slippage each side."""
    turnover = price * LOT
    rupees = 40 + stt * turnover + 0.000045 * 2 * turnover
    return rupees / LOT + 2.0


def load(iv):
    raw = pd.read_pickle(f"data/raw_{iv}.pkl")
    px = raw["^NSEI"][["Open", "High", "Low", "Close"]].dropna()
    vol = sum((raw[s]["Volume"].fillna(0) * raw[s]["Close"].ffill()) for s in STOCKS)
    df = px.join(vol.rename("Volume"))
    df.index = df.index.tz_localize(None)
    if iv == "60m":  # rebuild the missing 09:15 bar volume from daily turnover
        d = pd.read_pickle("data/raw_1d.pkl")
        dvol = sum((d[s]["Volume"].fillna(0) * d[s]["Close"].ffill()) for s in STOCKS)
        day = df.index.normalize()
        rest = df["Volume"].groupby(day).transform("sum")
        first = df.index.time == pd.Timestamp("09:15").time()
        fill = dvol.reindex(day).values - rest.values
        df.loc[first, "Volume"] = np.where(fill > 0, fill, np.nan)[first]
        df["Volume"] = df["Volume"].replace(0, np.nan)
        df["Volume"] = df["Volume"].fillna(df["Volume"].groupby(df.index.time).transform("median"))
    else:
        df["Volume"] = df["Volume"].replace(0, np.nan).ffill()
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n):
    pc = df.Close.shift()
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df, n=10, m=3.0):
    a = atr(df, n).values
    hl2 = ((df.High + df.Low) / 2).values
    c = df.Close.values
    ub, lb = hl2 + m * a, hl2 - m * a
    fu, fl = ub.copy(), lb.copy()
    st = np.full(len(c), np.nan); dirn = np.ones(len(c))
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if dirn[i - 1] == 1 and c[i] < fl[i]: dirn[i] = -1
        elif dirn[i - 1] == -1 and c[i] > fu[i]: dirn[i] = 1
        else: dirn[i] = dirn[i - 1]
        st[i] = fl[i] if dirn[i] == 1 else fu[i]
    return pd.Series(st, df.index), pd.Series(dirn, df.index)


def indicators(df, htf_mult):
    df = df.copy()
    df["st"], df["st_dir"] = supertrend(df, 10, 3)
    df["e9"], df["e21"] = ema(df.Close, 9), ema(df.Close, 21)
    # higher timeframe EMA9/21 approximated on the same bars (x htf_mult)
    df["h9"], df["h21"] = ema(df.Close, 9 * htf_mult), ema(df.Close, 21 * htf_mult)
    df["atr"] = atr(df, 14)
    dc = df.Close.groupby(df.index.normalize()).last()
    d_up = (dc > ema(dc, 20)).shift()   # known at today's open
    df["d_up"] = d_up.reindex(df.index.normalize()).fillna(False).astype(bool).values
    day = df.index.normalize()
    tp = (df.High + df.Low + df.Close) / 3
    df["vwap"] = (tp * df.Volume).groupby(day).cumsum() / df.Volume.groupby(day).cumsum()
    # relative volume vs the same time-of-day over the previous 10 sessions
    tod = df.index.time
    df["rvol"] = df.Volume / df.Volume.groupby(tod).transform(lambda s: s.shift().rolling(10, 3).mean())
    return df


def backtest(df, p):
    """p: dict of params. Signals evaluated on bar close, entered at that close."""
    long_ok = (df.Close > df.st) & (df.Close > df.e21) & (df.e9 > df.e21) & (df.h9 > df.h21)
    short_ok = (df.Close < df.st) & (df.Close < df.e21) & (df.e9 < df.e21) & (df.h9 < df.h21)
    if p["vol"]:
        long_ok &= df.rvol > p["vol"]; short_ok &= df.rvol > p["vol"]
    if p["vwap"]:
        long_ok &= df.Close > df.vwap; short_ok &= df.Close < df.vwap
    mode = p.get("mode", "state")
    if mode == "fresh":       # condition must turn true on this bar (not carried over)
        long_ok = long_ok & ~long_ok.shift(fill_value=False)
        short_ok = short_ok & ~short_ok.shift(fill_value=False)
    elif mode == "pullback":  # trend state + bar dipped to EMA21/VWAP and closed back in trend
        lvl_l = np.minimum(df.e21, df.vwap); lvl_s = np.maximum(df.e21, df.vwap)
        trend_l = (df.st_dir == 1) & (df.h9 > df.h21) & (df.e9 > df.e21)
        trend_s = (df.st_dir == -1) & (df.h9 < df.h21) & (df.e9 < df.e21)
        long_ok = trend_l & (df.Low <= lvl_l) & (df.Close > lvl_l) & (df.Close > df.Open)
        short_ok = trend_s & (df.High >= lvl_s) & (df.Close < lvl_s) & (df.Close < df.Open)
        if p["vol"]:
            long_ok &= df.rvol > p["vol"]; short_ok &= df.rvol > p["vol"]
    if p.get("daily"):        # trade only with the daily trend (prev day close vs daily EMA20)
        long_ok &= df.d_up; short_ok &= ~df.d_up
    h_exit_long = (df.h9 < df.h21) & (df.h9.shift() >= df.h21.shift())
    h_exit_short = (df.h9 > df.h21) & (df.h9.shift() <= df.h21.shift())

    t = df.index
    tm = t.hour * 60 + t.minute
    o, h, l, c = df.Open.values, df.High.values, df.Low.values, df.Close.values
    a, stl = df.atr.values, df.st.values
    bar = p["bar_min"]
    trades, pos, day_count, cur_day = [], None, 0, None
    for i in range(30, len(df)):
        d = t[i].normalize()
        if d != cur_day:
            cur_day, day_count = d, 0
        close_t = tm[i] + bar  # bar close time in minutes
        if pos:  # manage open position on this bar
            side, entry, sl, tp_ = pos["side"], pos["entry"], pos["sl"], pos["tp"]
            ex = None
            hit_sl = (l[i] <= sl) if side == 1 else (h[i] >= sl)
            hit_tp = (h[i] >= tp_) if side == 1 else (l[i] <= tp_)
            gap_sl = (o[i] <= sl) if side == 1 else (o[i] >= sl)   # overnight/bar gap through SL
            gap_tp = (o[i] >= tp_) if side == 1 else (o[i] <= tp_)
            if gap_sl: ex = (o[i], "SL")
            elif gap_tp: ex = (o[i], "TP")
            elif hit_sl and hit_tp: ex = (tp_, "TP") if p.get("tp_first") else (sl, "SL")  # default: SL first
            elif hit_sl: ex = (sl, "SL")
            elif hit_tp: ex = (tp_, "TP")
            if not ex and p.get("be") and not pos.get("be_done"):   # move SL to cost after +1R
                fav = (h[i] - entry) if side == 1 else (entry - l[i])
                if fav >= pos["risk"]:
                    pos["sl"] = entry + side * 2; pos["be_done"] = True
            if not ex:
                fav = (h[i] - entry) if side == 1 else (entry - l[i])
                pos["best"] = max(pos.get("best", 0), fav)
                if p.get("be_at") and pos["best"] >= p["be_at"] * pos["risk"]:      # SL to cost (+2) after X R
                    pos["sl"] = max(pos["sl"], entry + 2) if side == 1 else min(pos["sl"], entry - 2)
                if p.get("trail_pts") and pos["best"] >= p.get("trail_start", 1) * pos["risk"]:
                    lvl = entry + side * (pos["best"] - p["trail_pts"])
                    pos["sl"] = max(pos["sl"], lvl) if side == 1 else min(pos["sl"], lvl)
                pos["bars"] = pos.get("bars", 0) + 1
                if p.get("time_stop") and pos["bars"] >= p["time_stop"]:
                    ex = (c[i], "TIME")
                elif p.get("exit_ema") and ((side == 1 and df.e9.iat[i] < df.e21.iat[i]) or (side == -1 and df.e9.iat[i] > df.e21.iat[i])):
                    ex = (c[i], "EMA")
                elif p.get("exit_e21") and ((side == 1 and c[i] < df.e21.iat[i]) or (side == -1 and c[i] > df.e21.iat[i])):
                    ex = (c[i], "E21")
                elif p.get("exit_st") and ((side == 1 and c[i] < stl[i]) or (side == -1 and c[i] > stl[i])):
                    ex = (c[i], "ST")
                elif p.get("exit_vwap") and ((side == 1 and c[i] < df.vwap.iat[i]) or (side == -1 and c[i] > df.vwap.iat[i])):
                    ex = (c[i], "VWAP")
            if not ex and p["sig_exit"] and ((side == 1 and h_exit_long.iat[i]) or (side == -1 and h_exit_short.iat[i])):
                ex = (c[i], "SIG")
            if not ex and close_t >= p["sq_off"]:
                ex = (c[i], "EOD")
            if ex:
                pts = (ex[0] - entry) * side
                trades.append(dict(entry_time=pos["t"], exit_time=t[i], side=side, entry=entry, exit=ex[0],
                                   reason=ex[1], risk=pos["risk"], pts=pts,
                                   net=pts - cost_points(entry, p.get("stt", 0.0002))))
                pos = None
            continue
        if day_count >= p["max_trades"] or t[i].dayofweek not in p["days"]:
            continue
        if close_t < p["start"] or close_t > p["no_trade_after"]:
            continue
        side = 1 if long_ok.iat[i] else (-1 if short_ok.iat[i] else 0)
        if not side:
            continue
        entry = c[i]
        if p["sl"] == "st":
            risk = abs(entry - stl[i])
            risk = min(max(risk, 0.5 * a[i]), 3 * a[i])
        elif p["sl"] == "pts":
            risk = p["sl_pts"]
        else:
            risk = p["sl"] * a[i]
        pos = dict(side=side, entry=entry, risk=risk, t=t[i],
                   sl=entry - side * risk, tp=entry + side * risk * p["rr"])
        day_count += 1
    return pd.DataFrame(trades)


def stats(tr):
    if tr.empty:
        return dict(trades=0)
    n = tr.net
    eq = (n * LOT).cumsum()
    dd = (eq - eq.cummax()).min()
    wins = n[n > 0].sum(); loss = -n[n <= 0].sum()
    return dict(trades=len(tr), win=round((n > 0).mean() * 100, 1),
                net_pts=round(n.sum(), 0), net_rs=round(n.sum() * LOT, 0),
                pf=round(wins / loss, 2) if loss else np.inf,
                avg_rs=round(n.mean() * LOT, 0), maxdd_rs=round(dd, 0),
                tp_hits=int((tr.reason == "TP").sum()), sl_hits=int((tr.reason == "SL").sum()))
