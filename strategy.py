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


def next_expiry(ts: pd.Timestamp) -> datetime:
    """Next weekly expiry. On expiry day itself we roll to the next week."""
    d = ts.date()
    days = (EXPIRY_WEEKDAY - d.weekday()) % 7
    if days == 0:
        days = 7
    return datetime.combine(d + timedelta(days=days), time(15, 30))


def years_to(ts: pd.Timestamp, expiry: datetime) -> float:
    return max((expiry - ts.tz_localize(None).to_pydatetime()).total_seconds(), 60) / (365 * 86400)


def spread_value(S, ts, legs, expiry, atm_iv):
    """Value (in points) of short-leg minus long-leg = what it costs to close."""
    T = years_to(ts, expiry)
    (ks, kind), (kl, _) = legs
    short = bs_price(S, ks, T, strike_iv(atm_iv, S, ks, kind), kind)
    long_ = bs_price(S, kl, T, strike_iv(atm_iv, S, kl, kind), kind)
    return short, long_


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
        if day not in vix_prev.index or pd.isna(vix_prev.loc[day]):
            continue
        entry_ts, entry = idx[i + 1], o[i + 1]
        atm_iv = float(vix_prev.loc[day]) / 100
        k = round(entry / STRIKE_STEP) * STRIKE_STEP
        if side == 1:
            ks = k + p.short_offset
            legs = ((ks, "P"), (ks - p.hedge, "P"))
        else:
            ks = k - p.short_offset
            legs = ((ks, "C"), (ks + p.hedge, "C"))
        exp = next_expiry(entry_ts)
        s_in, l_in = spread_value(entry, entry_ts, legs, exp, atm_iv)
        pos = dict(side=side, day=dates[i + 1], entry_ts=entry_ts, entry=entry, legs=legs,
                   expiry=exp, iv=atm_iv, short_in=s_in, long_in=l_in,
                   sl_lvl=entry - side * p.sl,
                   tgt=entry + side * p.rr * p.sl if p.exit_mode not in ("trail", "lock_ride") else None,
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
    s_out, l_out = spread_value(exit_px, exit_ts, pos["legs"], pos["expiry"], pos["iv"])
    credit = pos["short_in"] - pos["long_in"]
    debit = s_out - l_out
    gross = (credit - debit) * LOT_SIZE
    sell_prem = pos["short_in"] + l_out          # premium we SOLD (entry short, exit hedge)
    buy_prem = pos["long_in"] + s_out            # premium we BOUGHT (entry hedge, exit short)
    cost = charges(sell_prem, buy_prem) + 4 * p.slip * LOT_SIZE
    return dict(
        signal_ts=pos["signal_ts"], entry_ts=pos["entry_ts"], exit_ts=exit_ts,
        side="BULL PUT" if pos["side"] == 1 else "BEAR CALL",
        short_strike=pos["legs"][0][0], hedge_strike=pos["legs"][1][0],
        spot_in=round(pos["entry"], 2), spot_out=round(float(exit_px), 2),
        spot_pts=round((exit_px - pos["entry"]) * pos["side"], 2),
        credit=round(credit, 2), close_cost=round(debit, 2),
        gross=round(gross, 2), costs=round(cost, 2), net=round(gross - cost, 2),
        reason=reason, iv=pos["iv"],
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
