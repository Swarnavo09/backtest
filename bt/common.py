"""
Shared building blocks: data loading, candles, indicators (Supertrend, ADX, ATR),
NSE expiry calendar, lot sizes, Black-Scholes option pricing and transaction costs.

IMPORTANT MODELLING NOTE
------------------------
No historical NIFTY option-chain data is available in this environment, so option
premiums are *modelled* with Black-Scholes:
  * ATM implied vol = 1.2 x EWMA realised volatility of daily NIFTY returns (lambda 0.94),
    known before the day starts (no look-ahead), clipped to 9%..45%.  India VIX has
    historically traded around 1.1-1.3x realised vol, so this is a VIX proxy.
  * Skew: OTM puts get +0.9 vol points per 1% out-of-the-money, OTM calls -0.2 per 1%.
  * IV is held constant through the day (no intraday IV spikes/crush).
P&L is therefore an estimate. Real fills, IV moves and bid-ask can differ.
"""
import math
import os

import numpy as np
import pandas as pd

_erf = np.vectorize(math.erf, otypes=[float])


class norm:  # tiny stand-in for scipy.stats.norm (keeps dependencies to pandas + numpy)
    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nifty_1m.parquet")
RISK_FREE = 0.065
STRIKE_STEP = 50

# ----------------------------------------------------------------------------- data


def load_1m():
    return pd.read_parquet(DATA)


def candles(df1, minutes):
    """Resample 1-min bars to N-minute candles aligned to 09:15 (like a broker chart).
    Index = candle START time; column 'end' = time the candle closes."""
    b = df1.resample(f"{minutes}min", origin="start_day", offset="9h15min", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    b["end"] = b.index + pd.Timedelta(minutes=minutes)
    # last candle of the day ends at 15:30, not later
    close_t = pd.to_datetime(b.index.date.astype(str)) + pd.Timedelta(hours=15, minutes=30)
    b["end"] = np.minimum(b["end"].values, close_t.values)
    return b


def daily(df1):
    d = df1.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    d["pc"] = d.Close.shift()
    tr = pd.concat([d.High - d.Low, (d.High - d.pc).abs(), (d.Low - d.pc).abs()], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(14).mean().shift()  # known before the session opens
    r = np.log(d.Close).diff()
    ewm_var = (r ** 2).ewm(alpha=0.06, adjust=False).mean()  # RiskMetrics lambda = 0.94
    d["iv"] = (np.sqrt(ewm_var * 252) * 1.2).clip(0.09, 0.45).shift()  # IV proxy known pre-open
    return d

# ----------------------------------------------------------------------------- indicators


def rma(x, n):
    """Wilder's moving average (what TradingView/most brokers use for ATR, ADX)."""
    return x.ewm(alpha=1.0 / n, adjust=False).mean()


def atr(b, n):
    pc = b.Close.shift()
    tr = pd.concat([b.High - b.Low, (b.High - pc).abs(), (b.Low - pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def supertrend(b, period=10, mult=3.0):
    """Classic Supertrend. Returns (line, direction) where direction = +1 green (bullish), -1 red."""
    a = atr(b, period).values
    hl2 = ((b.High + b.Low) / 2).values
    c = b.Close.values
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb = ub.copy(), lb.copy()
    dirn = np.ones(len(b), dtype=int)
    line = np.full(len(b), np.nan)
    for i in range(1, len(b)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if dirn[i - 1] == -1:
            dirn[i] = 1 if c[i] > fub[i - 1] else -1
        else:
            dirn[i] = -1 if c[i] < flb[i - 1] else 1
        line[i] = flb[i] if dirn[i] == 1 else fub[i]
    return pd.Series(line, b.index), pd.Series(dirn, b.index)


def adx(b, n=14):
    up = b.High.diff()
    dn = -b.Low.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), b.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), b.index)
    tr = atr(b, n)
    pdi = 100 * rma(pdm, n) / tr
    ndi = 100 * rma(ndm, n) / tr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return rma(dx.fillna(0), n)

# ----------------------------------------------------------------------------- contract specs


def lot_size(day):
    """NIFTY lot size in force on a date (NSE revisions: 50 -> 75 on 20-Nov-2024 -> 65 from Jan-2026)."""
    day = pd.Timestamp(day)
    if day < pd.Timestamp("2024-11-20"):
        return 50
    if day < pd.Timestamp("2026-01-01"):
        return 75
    return 65


class ExpiryCalendar:
    """Weekly NIFTY expiries: Thursday until Aug-2025, Tuesday from Sep-2025.
    If the expiry weekday is a market holiday, expiry moves to the previous trading day."""

    def __init__(self, trading_days):
        self.td = pd.DatetimeIndex(sorted(set(pd.to_datetime(trading_days).normalize())))
        self.last = self.td[-1]

    def _shift(self, d):
        while d <= self.last and d not in self.td:
            d -= pd.Timedelta(days=1)
        return d

    def expiries_from(self, day, n=3):
        day = pd.Timestamp(day).normalize()
        out, d = [], day
        while len(out) < n:
            wd = 3 if d < pd.Timestamp("2025-09-01") else 1  # Thu / Tue
            if d.weekday() == wd:
                e = self._shift(d)
                if e >= day and (not out or e > out[-1]):
                    out.append(e)
            d += pd.Timedelta(days=1)
        return out

    def pick(self, day):
        """User rule: Wed/Thu -> this week's expiry, Fri..Tue -> next week's (Tuesday-expiry regime).
        Generalised to any expiry weekday: use the nearest expiry if it is >= 5 calendar days away,
        otherwise the one after it.  (Tue-expiry regime: Wed=6d, Thu=5d -> nearest; Fri=4d, Mon=1d,
        Tue=0d -> next.  Same 5-day rule applied in the Thursday-expiry years.)"""
        day = pd.Timestamp(day).normalize()
        e = self.expiries_from(day, 2)
        return e[0] if (e[0] - day).days >= 5 else e[1]

# ----------------------------------------------------------------------------- option pricing


def iv_for(strike, spot, atm_iv, kind):
    otm_pct = (spot - strike) / spot * 100 if kind == "P" else (strike - spot) / spot * 100
    otm_pct = max(otm_pct, 0.0)
    slope = 0.009 if kind == "P" else -0.002
    return max(atm_iv + slope * otm_pct, 0.6 * atm_iv)


def bs_price(spot, strike, t_years, vol, kind):
    """Vectorised Black-Scholes (spot can be a numpy array)."""
    spot = np.asarray(spot, dtype=float)
    t = max(t_years, 1.0 / (365 * 24 * 60))
    sq = vol * math.sqrt(t)
    d1 = (np.log(spot / strike) + (RISK_FREE + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    disc = strike * math.exp(-RISK_FREE * t)
    if kind == "C":
        return spot * norm.cdf(d1) - disc * norm.cdf(d2)
    return disc * norm.cdf(-d2) - spot * norm.cdf(-d1)


def years_to_expiry(now, expiry):
    exp_t = pd.Timestamp(expiry).normalize() + pd.Timedelta(hours=15, minutes=30)
    return max((exp_t - pd.Timestamp(now)).total_seconds(), 60) / (365 * 24 * 3600)


def spread_value(spot, now, expiry, short_k, long_k, kind, atm_iv, ref_spot):
    """Value of (short leg - long leg) per unit. Skew is anchored to the spot at entry (sticky strike)."""
    t = years_to_expiry(now, expiry)
    vs, vl = iv_for(short_k, ref_spot, atm_iv, kind), iv_for(long_k, ref_spot, atm_iv, kind)
    return bs_price(spot, short_k, t, vs, kind) - bs_price(spot, long_k, t, vl, kind)

# ----------------------------------------------------------------------------- costs


SLIPPAGE_PTS = 0.5  # per leg, per execution (half a point against us on every fill)


def charges(day, buy_turnover, sell_turnover, n_orders):
    """Indian F&O option charges (approx., discount broker). Turnover in rupees of premium."""
    day = pd.Timestamp(day)
    brokerage = 20.0 * n_orders
    stt = sell_turnover * (0.001 if day >= pd.Timestamp("2024-10-01") else 0.000625)
    txn = (buy_turnover + sell_turnover) * (0.0003503 if day >= pd.Timestamp("2024-10-01") else 0.000495)
    sebi = (buy_turnover + sell_turnover) * 10 / 1e7
    stamp = buy_turnover * 0.00003
    gst = 0.18 * (brokerage + txn + sebi)
    return brokerage + stt + txn + sebi + stamp + gst
