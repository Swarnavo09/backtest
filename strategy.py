"""Hedged Nifty option-selling strategy: EMA + MACD + Supertrend confluence.

Signals come from the Nifty 50 spot chart. On a bullish confluence we open a
BULL PUT SPREAD (sell ATM PE, buy a lower PE as hedge); on a bearish confluence
we open a BEAR CALL SPREAD (sell ATM CE, buy a higher CE as hedge).

Stop-loss and target are measured in NIFTY SPOT points (target = RR x SL).
The rupee P&L of every trade is the change in the spread's value, priced with
Black-Scholes at entry and exit (India VIX of the previous day as the ATM IV,
plus a small skew), after brokerage, taxes and slippage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd

LOT_SIZE = 65          # Nifty lot size from Jan 2026
STRIKE_STEP = 50
RISK_FREE = 0.065
EXPIRY_WEEKDAY = 1     # Tuesday (Nifty weekly expiry since Sep 2025)


# ----------------------------------------------------------------- indicators
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, sig)


def supertrend(df: pd.DataFrame, period=10, mult=3.0):
    """Classic Supertrend. Returns (direction +1/-1, line)."""
    h, l, c = df.High.values, df.Low.values, df.Close.values
    n = len(df)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])])
    atr = np.empty(n)
    atr[0] = tr[0]
    for i in range(1, n):                       # Wilder's RMA, like TradingView
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    mid = (h + l) / 2
    bu, bl = mid + mult * atr, mid - mult * atr
    fu, fl = bu.copy(), bl.copy()
    d = np.ones(n, dtype=int)
    for i in range(1, n):
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = d[i - 1]
        if d[i - 1] == -1 and c[i] > fu[i - 1]:
            d[i] = 1
        elif d[i - 1] == 1 and c[i] < fl[i - 1]:
            d[i] = -1
    line = np.where(d == 1, fl, fu)
    return pd.Series(d, index=df.index), pd.Series(line, index=df.index)


# ------------------------------------------------------------- option pricing
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, iv, kind, r=RISK_FREE):
    if T <= 0:
        return max(0.0, S - K) if kind == "C" else max(0.0, K - S)
    sd = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / sd
    d2 = d1 - sd
    if kind == "C":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def strike_iv(atm_iv, S, K, kind):
    """Simple Nifty skew: OTM puts richer, OTM calls slightly cheaper."""
    otm_pct = (S - K) / S * 100 if kind == "P" else (K - S) / S * 100
    otm_pct = max(otm_pct, 0.0)
    adj = 0.010 * otm_pct if kind == "P" else -0.003 * otm_pct
    return max(atm_iv + adj, 0.05)


def expiry_weekday(d) -> int:
    """Nifty weekly expiry: Thursday until Aug 2025, Tuesday from 1 Sep 2025."""
    return 3 if d < datetime(2025, 9, 1).date() else EXPIRY_WEEKDAY


def next_expiry(ts: pd.Timestamp) -> datetime:
    """Next weekly expiry. On expiry day itself we roll to the next week."""
    d = ts.date()
    x = d + timedelta(days=1)                   # strictly after today: roll on expiry day
    while x.weekday() != expiry_weekday(x):
        x += timedelta(days=1)
    return datetime.combine(x, time(15, 30))


def years_to(ts: pd.Timestamp, expiry: datetime) -> float:
    return max((expiry - ts.tz_localize(None).to_pydatetime()).total_seconds(), 60) / (365 * 86400)


def spread_value(S, ts, legs, expiry, atm_iv):
    """Value (in points) of short-leg minus long-leg = what it costs to close."""
    T = years_to(ts, expiry)
    (ks, kind), (kl, _) = legs
    short = bs_price(S, ks, T, strike_iv(atm_iv, S, ks, kind), kind)
    long_ = bs_price(S, kl, T, strike_iv(atm_iv, S, kl, kind), kind)
    return short, long_


# Pluggable pricing: the default uses India VIX + a simple skew and calendar time.
# realiv.py swaps these for real implied vols from NSE bhavcopies.
def _default_iv(day, entry_ts, legs, expiry, vix_prev):
    if day not in vix_prev.index or pd.isna(vix_prev.loc[day]):
        return None
    return float(vix_prev.loc[day]) / 100


def _default_price(S, ts, legs, expiry, iv):
    return spread_value(S, ts, legs, expiry, iv)


PRICING = {"expiry": lambda ts, p: next_expiry(ts), "iv": _default_iv, "price": _default_price}


def charges(sell_prem_total, buy_prem_total, lots=1):
    """Indian F&O option charges for one round-trip of a 2-leg spread (4 orders)."""
    q = LOT_SIZE * lots
    turnover = (sell_prem_total + buy_prem_total) * q
    brokerage = 4 * 20.0
    stt = 0.001 * sell_prem_total * q            # 0.1% on option sell premium
    txn = 0.0003503 * turnover                   # NSE transaction charge
    sebi = turnover * 10 / 1e7
    stamp = 0.00003 * buy_prem_total * q
    gst = 0.18 * (brokerage + txn + sebi)
    return brokerage + stt + txn + sebi + stamp + gst


# ------------------------------------------------------------------ params
@dataclass(frozen=True)
class Params:
    tf: int = 5                  # minutes: 5 / 10 / 15
    ma_fast: int = 9
    ma_slow: int = 21
    st_period: int = 10
    st_mult: float = 3.0
    macd_zero: bool = False      # also require MACD line above/below zero
    sl: float = 30.0             # stop-loss in Nifty spot points
    rr: float = 2.0              # target = rr * sl
    exit_mode: str = "fixed"     # fixed | be | step | trail | lock_ride
    st_exit: bool = False        # also exit when Supertrend flips against us
    hedge: int = 200             # hedge distance in points (from the short strike)
    short_offset: int = 0        # +100 = sell 100 pts ITM, -100 = sell 100 pts OTM
    htf: bool = False            # only trade in the direction of the 1-hour Supertrend
    max_trades: int = 2
    slip: float = 0.5            # slippage per leg per side, in points
    lots: int = 1                # lots per leg (brokerage is per order, so it does not scale)
    dte0: bool = False           # allow trading the expiring weekly on expiry day (real-IV pricing only)
    start: time = time(9, 30)    # earliest signal-candle close
    last_entry: time = time(14, 30)
    squareoff: time = time(15, 15)


# ----------------------------------------------------------------- data prep
def load_bars(path_5m: str, tf: int) -> pd.DataFrame:
    df = pd.read_csv(path_5m, index_col=0, parse_dates=True)
    df = df[["Open", "High", "Low", "Close"]]
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Asia/Kolkata")
    if tf != 5:
        df = (df.resample(f"{tf}min", offset="15min" if tf == 15 else "5min")
                .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
                .dropna())
    return df


def htf_direction(df5: pd.DataFrame, minutes: int = 60, period=10, mult=3.0) -> pd.Series:
    """1-hour Supertrend direction, stamped at the time each hourly candle CLOSES."""
    h = (df5.resample(f"{minutes}min", offset="15min")
            .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna())
    d, _ = supertrend(h, period, mult)
    # last hourly candle of the day closes at 15:30, not start + 60 min
    close_ts = [min(t + pd.Timedelta(minutes=minutes), t.normalize() + pd.Timedelta(hours=15, minutes=30))
                for t in h.index]
    return pd.Series(d.values, index=pd.DatetimeIndex(close_ts))


def add_indicators(df: pd.DataFrame, p: Params, htf: pd.Series | None = None) -> pd.DataFrame:
    out = df.copy()
    out["ema_f"] = ema(out.Close, p.ma_fast)
    out["ema_s"] = ema(out.Close, p.ma_slow)
    out["macd"], out["sig"] = macd(out.Close)
    out["st_dir"], out["st_line"] = supertrend(out, p.st_period, p.st_mult)
    bull = (out.Close > out.ema_s) & (out.ema_f > out.ema_s) & (out.macd > out.sig) & (out.st_dir == 1)
    bear = (out.Close < out.ema_s) & (out.ema_f < out.ema_s) & (out.macd < out.sig) & (out.st_dir == -1)
    if p.macd_zero:
        bull &= out.macd > 0
        bear &= out.macd < 0
    if p.htf:
        if htf is None:
            raise ValueError("htf series required when p.htf is True")
        sig_close = out.index + pd.Timedelta(minutes=p.tf)
        hd = htf.reindex(htf.index.union(sig_close)).ffill().reindex(sig_close).values
        out["htf_dir"] = hd
        bull &= out.htf_dir == 1
        bear &= out.htf_dir == -1
    out["bull"], out["bear"] = bull, bear
    return out


# -------------------------------------------------------------------- engine
def backtest(df: pd.DataFrame, vix: pd.Series, p: Params) -> pd.DataFrame:
    """df must already carry indicators for p. Returns one row per trade."""
    idx = df.index
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    bull, bear, st_dir = df.bull.values, df.bear.values, df.st_dir.values
    tfd = timedelta(minutes=p.tf)
    dates = np.array([t.date() for t in idx])
    times = np.array([t.time() for t in idx])
    close_times = np.array([(t + tfd).time() for t in idx])
    vix_prev = vix.shift(1)

    trades = []
    pos = None
    trades_today, cur_day = 0, None

    for i in range(1, len(df) - 1):
        if dates[i] != cur_day:
            cur_day, trades_today = dates[i], 0

        # ------------------------------------------------ manage open position
        if pos is not None:
            j = i
            side = pos["side"]
            exit_px, reason = None, None
            if times[j] >= p.squareoff or dates[j] != pos["day"]:
                exit_px, reason = o[j], "time"
            else:
                sl_lvl, tgt = pos["sl_lvl"], pos["tgt"]
                if side == 1:
                    if l[j] <= sl_lvl:
                        exit_px, reason = min(sl_lvl, o[j]), ("sl" if sl_lvl < pos["entry"] else "trail")
                    elif tgt is not None and h[j] >= tgt:
                        exit_px, reason = max(tgt, o[j]), "target"
                else:
                    if h[j] >= sl_lvl:
                        exit_px, reason = max(sl_lvl, o[j]), ("sl" if sl_lvl > pos["entry"] else "trail")
                    elif tgt is not None and l[j] <= tgt:
                        exit_px, reason = min(tgt, o[j]), "target"
                if exit_px is None and p.st_exit and st_dir[j] != side:
                    exit_px, reason = c[j], "st_flip"
            if exit_px is not None:
                trades.append(_close(pos, exit_px, idx[j], reason, p))
                pos = None
            else:
                _update_trail(pos, h[j], l[j], c[j], p)
            if pos is not None:
                continue

        # --------------------------------------------------------- new entry
        if trades_today >= p.max_trades:
            continue
        if not (p.start <= close_times[i] <= p.last_entry):
            continue
        side = 1 if (bull[i] and not bull[i - 1]) else (-1 if (bear[i] and not bear[i - 1]) else 0)
        if side == 0 or dates[i + 1] != dates[i]:
            continue
        day = pd.Timestamp(dates[i])
        entry_ts, entry = idx[i + 1], o[i + 1]
        k = round(entry / STRIKE_STEP) * STRIKE_STEP
        if side == 1:
            ks = k + p.short_offset
            legs = ((ks, "P"), (ks - p.hedge, "P"))
        else:
            ks = k - p.short_offset
            legs = ((ks, "C"), (ks + p.hedge, "C"))
        exp = PRICING["expiry"](entry_ts, p)
        if exp is None:
            continue
        atm_iv = PRICING["iv"](day, entry_ts, legs, exp, vix_prev)
        if atm_iv is None:
            continue
        s_in, l_in = PRICING["price"](entry, entry_ts, legs, exp, atm_iv)
        pos = dict(side=side, day=dates[i + 1], entry_ts=entry_ts, entry=entry, legs=legs,
                   expiry=exp, iv=atm_iv, short_in=s_in, long_in=l_in,
                   sl_lvl=entry - side * p.sl,
                   tgt=entry + side * p.rr * p.sl if p.exit_mode not in ("trail", "lock_ride", "hold") else None,
                   best=entry, signal_ts=idx[i])
        if p.exit_mode == "lock_ride":
            pos["tgt"] = None
            pos["ride_from"] = entry + side * p.rr * p.sl
        trades_today += 1
        # the entry bar itself is managed on the next loop iteration (i + 1)

    if pos is not None:
        trades.append(_close(pos, c[-1], idx[-1], "eod_data", p))
    return pd.DataFrame(trades)


def _update_trail(pos, hi, lo, cl, p: Params):
    """Runs at each candle close while in a trade."""
    side, entry, R = pos["side"], pos["entry"], p.sl
    pos["best"] = max(pos["best"], hi) if side == 1 else min(pos["best"], lo)
    pos["worst"] = min(pos.get("worst", entry), lo) if side == 1 else max(pos.get("worst", entry), hi)
    fav = (pos["best"] - entry) * side            # best favourable move so far
    new = pos["sl_lvl"]
    if p.exit_mode in ("be", "step", "trail") and fav >= R:
        new = entry                                # move SL to cost at +1R
    if p.exit_mode == "step" and fav >= 1.5 * R:
        new = entry + side * 0.5 * R               # lock +0.5R at +1.5R
    if p.exit_mode == "trail" and fav >= R:
        new = pos["best"] - side * R               # trail 1R behind the best price
        new = max(new, entry) if side == 1 else min(new, entry)
    if p.exit_mode == "lock_ride":
        if fav >= R:
            new = entry
        if fav >= p.rr * R:                        # at 2R: lock +1R, keep trailing 1R
            new = pos["best"] - side * R
    pos["sl_lvl"] = max(pos["sl_lvl"], new) if side == 1 else min(pos["sl_lvl"], new)


def _close(pos, exit_px, exit_ts, reason, p: Params):
    s_out, l_out = PRICING["price"](exit_px, exit_ts, pos["legs"], pos["expiry"], pos["iv"])
    credit = pos["short_in"] - pos["long_in"]
    debit = s_out - l_out
    gross1 = (credit - debit) * LOT_SIZE          # per lot
    sell_prem = pos["short_in"] + l_out          # premium we SOLD (entry short, exit hedge)
    buy_prem = pos["long_in"] + s_out            # premium we BOUGHT (entry hedge, exit short)
    cost1 = charges(sell_prem, buy_prem, 1) + 4 * p.slip * LOT_SIZE
    gross = gross1 * p.lots
    cost = charges(sell_prem, buy_prem, p.lots) + 4 * p.slip * LOT_SIZE * p.lots
    return dict(
        signal_ts=pos["signal_ts"], entry_ts=pos["entry_ts"], exit_ts=exit_ts,
        side="BULL PUT" if pos["side"] == 1 else "BEAR CALL",
        short_strike=pos["legs"][0][0], hedge_strike=pos["legs"][1][0],
        spot_in=round(pos["entry"], 2), spot_out=round(float(exit_px), 2),
        spot_pts=round((exit_px - pos["entry"]) * pos["side"], 2),
        credit=round(credit, 2), close_cost=round(debit, 2),
        gross=round(gross, 2), costs=round(cost, 2), net=round(gross - cost, 2),
        net_1lot=round(gross1 - cost1, 2), costs_1lot=round(cost1, 2), lots=p.lots,
        reason=reason, iv=str(pos["iv"]),
        mfe=round((pos["best"] - pos["entry"]) * pos["side"], 2),
        mae=round((pos.get("worst", pos["entry"]) - pos["entry"]) * pos["side"], 2),
    )


# ------------------------------------------------------------------ metrics
def summarize(tr: pd.DataFrame, n_days: int) -> dict:
    if tr.empty:
        return dict(trades=0, net=0.0, win_rate=0.0, pf=0.0, avg=0.0, max_dd=0.0,
                    rf=0.0, avg_win=0.0, avg_loss=0.0, best=0.0, worst=0.0, per_day=0.0)
    net = tr.net
    eq = net.cumsum()
    dd = (eq - eq.cummax().clip(lower=0)).min()
    wins, losses = net[net > 0], net[net <= 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return dict(
        trades=len(tr), net=round(net.sum(), 0), win_rate=round(100 * len(wins) / len(tr), 1),
        pf=round(pf, 2), avg=round(net.mean(), 0), max_dd=round(dd, 0),
        rf=round(net.sum() / -dd, 2) if dd < 0 else float("inf"),
        avg_win=round(wins.mean(), 0) if len(wins) else 0.0,
        avg_loss=round(losses.mean(), 0) if len(losses) else 0.0,
        best=round(net.max(), 0), worst=round(net.min(), 0),
        per_day=round(net.sum() / n_days, 0),
    )


def params_dict(p: Params) -> dict:
    d = asdict(p)
    for k in ("start", "last_entry", "squareoff"):
        d.pop(k)
    return d


# ------------------------------------------------- v2: weekly / daily bias
def bias_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly and daily candle colour, both 'live' (as of this candle's close) and
    'prev' (last completed candle). Nothing here looks ahead."""
    out = pd.DataFrame(index=df.index)
    day = pd.Series(df.index.date, index=df.index)
    wk = pd.Series(df.index.tz_localize(None).to_period("W-SUN").astype(str), index=df.index)
    day_open = df.Open.groupby(day).transform("first")
    week_open = df.Open.groupby(wk).transform("first")
    out["d_live"] = np.sign(df.Close - day_open)
    out["w_live"] = np.sign(df.Close - week_open)
    d = df.groupby(day).agg(o=("Open", "first"), c=("Close", "last"))
    d_prev = np.sign(d.c - d.o).shift(1)
    out["d_prev"] = day.map(d_prev).values
    w = df.groupby(wk).agg(o=("Open", "first"), c=("Close", "last"))
    w_prev = np.sign(w.c - w.o).shift(1)
    out["w_prev"] = wk.map(w_prev).values
    # "VWAP" for the index: Nifty spot has no volume, so every candle gets equal weight
    # (running average of typical price since 09:15), as charting platforms do for indices.
    tp = (df.High + df.Low + df.Close) / 3
    vw = tp.groupby(day).cumsum() / tp.groupby(day).cumcount().add(1)
    out["vwap"] = np.sign(df.Close - vw)
    return out


SIGSETS = {
    "st": ("st",), "st_ema": ("st", "ema"), "st_macd": ("st", "macd"),
    "ema_macd": ("ema", "macd"), "all3": ("st", "ema", "macd"),
}
BIAS = {
    "none": None,
    "live": ("w_live", "d_live"),     # this week so far AND today so far
    "prev": ("w_prev", "d_prev"),     # last completed week AND yesterday
    "wprev_dlive": ("w_prev", "d_live"),
    "wlive_dlive_prevday": ("w_live", "d_live", "d_prev"),
    "vwap": ("vwap",),                 # price above / below today's VWAP only
    "w_vwap": ("w_live", "vwap"),      # this week's candle + VWAP
}


def add_signals_v2(df: pd.DataFrame, sigset: str, bias: str, ma=(9, 21), st=(10, 3.0)) -> pd.DataFrame:
    out = df.copy()
    out["ema_f"], out["ema_s"] = ema(out.Close, ma[0]), ema(out.Close, ma[1])
    out["macd"], out["sig"] = macd(out.Close)
    out["st_dir"], out["st_line"] = supertrend(out, st[0], st[1])
    comp_bull = {"st": out.st_dir == 1, "ema": (out.Close > out.ema_s) & (out.ema_f > out.ema_s),
                 "macd": out.macd > out.sig}
    comp_bear = {"st": out.st_dir == -1, "ema": (out.Close < out.ema_s) & (out.ema_f < out.ema_s),
                 "macd": out.macd < out.sig}
    bull = np.logical_and.reduce([comp_bull[k] for k in SIGSETS[sigset]])
    bear = np.logical_and.reduce([comp_bear[k] for k in SIGSETS[sigset]])
    if BIAS[bias]:
        b = bias_columns(out)
        for col in BIAS[bias]:
            bull &= (b[col] > 0).values
            bear &= (b[col] < 0).values
    out["bull"], out["bear"] = bull, bear
    return out
