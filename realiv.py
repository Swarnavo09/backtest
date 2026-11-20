"""Price spreads with REAL implied vols from NSE bhavcopies and the real expiry calendar.

For a trade on day d, each leg's IV is backed out from that exact contract's closing
price on day d-1 (no look-ahead). Strikes that did not trade are interpolated from
neighbouring strikes of the same expiry. Time to expiry can be calendar or trading time.

    import realiv; realiv.install(conv="trd")   # then strategy.backtest uses real IVs
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

import strategy

ROOT = Path(__file__).parent
OPT_FILE = ROOT / "data" / "nifty_opt_bhav.csv.gz"     # override for other indices
SPOT_FILE = ROOT / "data" / "nifty_5m_5y.csv"
TRADE_MIN, YEAR_TRADE_MIN = 375, 252 * 375
R = strategy.RISK_FREE


def _bs_vec(S, K, T, iv, call):
    sd = iv * np.sqrt(T)
    d1 = (np.log(S / K) + (R + 0.5 * iv * iv) * T) / sd
    d2 = d1 - sd
    c = S * ndtr(d1) - K * np.exp(-R * T) * ndtr(d2)
    p = K * np.exp(-R * T) * ndtr(-d2) - S * ndtr(-d1)
    return np.where(call, c, p)


def _iv_vec(price, S, K, T, call):
    lo, hi = np.full(len(price), 0.01), np.full(len(price), 3.0)
    for _ in range(50):
        mid = (lo + hi) / 2
        too_high = _bs_vec(S, K, T, mid, call) > price
        hi = np.where(too_high, mid, hi)
        lo = np.where(too_high, lo, mid)
    iv = (lo + hi) / 2
    intrinsic = np.where(call, np.maximum(S - K, 0), np.maximum(K - S, 0))
    return np.where((price > intrinsic + 0.05) & (iv > 0.011) & (iv < 2.9), iv, np.nan)


class RealIV:
    def __init__(self, conv: str = "trd"):
        self.vixdyn = conv.endswith("v")     # e.g. "mix70v": scale each leg's IV by VIX(t) / VIX(prev close)
        self.conv = conv.rstrip("v")
        vx = pd.read_csv(ROOT / "data" / "indiavix_5m_5y.csv", index_col=0, parse_dates=True)
        vx.index = pd.to_datetime(vx.index, utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
        self.vx_t = vx.index.values
        self.vx_c = vx.Close.values
        self.vx_prev = vx.Close.groupby(vx.index.date).last().shift(1).to_dict()
        opt = pd.read_csv(OPT_FILE, parse_dates=["date", "expiry"])
        n5 = pd.read_csv(SPOT_FILE, index_col=0, parse_dates=True)
        n5.index = pd.to_datetime(n5.index, utc=True).tz_convert("Asia/Kolkata")
        spot = n5.Close.groupby(n5.index.date).last()
        self.days = sorted(spot.index)
        self.day_pos = {d: i for i, d in enumerate(self.days)}
        self.expiries = sorted({e.date() for e in opt.expiry.unique()})
        opt["d"] = opt.date.dt.date
        opt["e"] = opt.expiry.dt.date
        opt["S"] = opt.d.map(spot)
        opt = opt[(opt.close > 0.05) & (opt.volume > 0) & opt.S.notna()
                  & ((opt.strike - opt.S).abs() <= 1500) & (opt.e > opt.d)]
        T = np.array([self.T(datetime.combine(d, time(15, 30)), e) for d, e in zip(opt.d, opt.e)])
        opt = opt.assign(T=T)
        opt["iv"] = _iv_vec(opt.close.values, opt.S.values, opt.strike.values, opt["T"].values,
                            (opt.type == "CE").values)
        opt = opt.dropna(subset=["iv"])
        self.table = {}
        for (d, e, t), g in opt.groupby(["d", "e", "type"]):
            g = g.sort_values("strike")
            self.table[(d, e, t[0])] = (g.strike.values, g.iv.values)
        self.n_iv = len(opt)

    # ----------------------------------------------------------- time
    def T(self, ts: datetime, expiry) -> float:
        if self.conv.startswith("mix"):      # e.g. mix70 = 0.70 x trading time + 0.30 x calendar time
            w = int(self.conv[3:]) / 100
            return w * self._T("trd", ts, expiry) + (1 - w) * self._T("cal", ts, expiry)
        return self._T(self.conv, ts, expiry)

    def _T(self, conv, ts: datetime, expiry) -> float:
        if conv == "cal":
            return max((datetime.combine(expiry, time(15, 30)) - ts).total_seconds(), 60) / (365 * 86400)
        d = ts.date()
        start = max(ts, datetime.combine(d, time(9, 15)))
        today = max(0.0, (datetime.combine(d, time(15, 30)) - start).total_seconds() / 60)
        if d >= expiry:
            return max(today, 1.0) / YEAR_TRADE_MIN
        i = bisect.bisect_right(self.days, d)
        j = bisect.bisect_right(self.days, expiry)
        full = j - i
        if expiry > self.days[-1]:
            full += int(np.busday_count(self.days[-1] + timedelta(days=1), expiry + timedelta(days=1)))
        return (today + full * TRADE_MIN) / YEAR_TRADE_MIN

    # ------------------------------------------------------- lookups
    def leg_iv(self, prev_day, expiry, K, kind):
        key = (prev_day, expiry, kind)
        if key not in self.table:
            return None
        ks, ivs = self.table[key]
        if K <= ks[0]:
            return float(ivs[0]) if ks[0] - K <= 200 else None
        if K >= ks[-1]:
            return float(ivs[-1]) if K - ks[-1] <= 200 else None
        return float(np.interp(K, ks, ivs))

    def expiry_fn(self, ts, p):
        d = ts.date()
        k = bisect.bisect_left(self.expiries, d)
        if k < len(self.expiries) and self.expiries[k] == d and not getattr(p, "dte0", False):
            k += 1                                     # roll on expiry day unless 0-DTE allowed
        return self.expiries[k] if k < len(self.expiries) else None

    def iv_fn(self, day, entry_ts, legs, expiry, vix_prev):
        d = day.date() if hasattr(day, "date") else day
        i = self.day_pos.get(d)
        if not i:
            return None
        prev = self.days[i - 1]
        ivs = tuple(self.leg_iv(prev, expiry, K, kind) for K, kind in legs)
        return None if any(v is None for v in ivs) else ivs

    def vix_ratio(self, t: datetime) -> float:
        """VIX now (last 5-minute close at or before t) over VIX at yesterday's close."""
        i = np.searchsorted(self.vx_t, np.datetime64(t), side="right") - 1
        prev = self.vx_prev.get(t.date())
        if i < 0 or prev is None or not np.isfinite(prev):
            return 1.0
        return float(self.vx_c[i] / prev)

    def price_fn(self, S, ts, legs, expiry, ivs):
        t = ts.tz_localize(None).to_pydatetime() if hasattr(ts, "tz_localize") else ts
        T = self.T(t, expiry)
        k = self.vix_ratio(t) if self.vixdyn else 1.0
        (ks, kind), (kl, _) = legs
        return (strategy.bs_price(S, ks, T, ivs[0] * k, kind), strategy.bs_price(S, kl, T, ivs[1] * k, kind))


_INST = {}


def install(conv: str = "trd") -> RealIV:
    if conv not in _INST:
        _INST[conv] = RealIV(conv)
    r = _INST[conv]
    strategy.PRICING.update(expiry=r.expiry_fn, iv=r.iv_fn, price=r.price_fn)
    return r


def uninstall():
    strategy.PRICING.update(expiry=lambda ts, p: strategy.next_expiry(ts),
                            iv=strategy._default_iv, price=strategy._default_price)
