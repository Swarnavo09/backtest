"""
Fast, configurable version of the Supertrend credit-spread engine, used to test refinements.

With the default CONFIG it reproduces the user's original rules (bt/credit_spread.py); each
key below switches one rule so variants can be compared like-for-like.

Main differences from credit_spread.py: trade management is vectorised per trade with numpy
(about 10x faster), and the normal CDF uses a fast closed-form approximation
(Abramowitz-Stegun 7.1.26, error < 1.5e-7).
"""
import math

import numpy as np
import pandas as pd

from bt import common as C

CONFIG = dict(
    lots=4, margin_per_lot=40_000, daily_cap=5_000, max_trades=2, skip_after_losing_days=3,
    # ---- entry
    adx_min=20, window=("09:25", "14:00"), flip_candle_only=False,
    trend_filter_atr=None,     # e.g. 0.15 -> price must already be >= 0.15 x daily ATR from today's open
                               #              in the trade direction (trade WITH the day's move)
    htf_minutes=None,          # e.g. 60 -> 1-hour Supertrend must agree with the trade
    # ---- direction
    direction="follow",        # "follow" the flip (user rule) or "fade" it (sell the opposite spread)
    # ---- structure
    short_offset=100, width=500, expiry="rule",   # "rule" (>=5 calendar days) or "nearest" weekly
    # ---- exits
    stop="ladder",             # "ladder" (user % ladder) | "none" (no % stop: ST close / cap / 15:15 only)
    init_stop=-1.5, partial_at=3.0, st_exit=True, square_off="15:15",
    # ---- model
    time_model="calendar",     # "calendar" (BS calendar time) | "trading" (theta accrues in market hours only)
)

# ----------------------------------------------------------------------------- fast pricing
_A = (0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429)


def _ncdf(x):
    x = np.asarray(x, dtype=float)
    z = np.abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    y = 1.0 - (((((_A[4] * t + _A[3]) * t) + _A[2]) * t + _A[1]) * t + _A[0]) * t * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * y)


def _bs(spot, k, t, vol, kind):
    t = np.maximum(t, 1e-7)
    sq = vol * np.sqrt(t)
    d1 = (np.log(spot / k) + (C.RISK_FREE + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    disc = k * np.exp(-C.RISK_FREE * t)
    if kind == "C":
        return spot * _ncdf(d1) - disc * _ncdf(d2)
    return disc * _ncdf(-d2) - spot * _ncdf(-d1)


def _stop_ladder(peak, init):
    return np.where(peak < 1.5, init, np.where(peak < 2.0, 0.5, np.floor(peak) - 1.0))


class Lab:
    def __init__(self, df1):
        self.df1 = df1
        self.d = C.daily(df1)
        self.cal = C.ExpiryCalendar(self.d.index)
        self.td = self.d.index
        self._tf = {}
        self.m1 = {k: (v.index.values, v.Open.values, v.High.values, v.Low.values, v.Close.values)
                   for k, v in df1.groupby(df1.index.normalize())}

    def tf(self, minutes):
        if minutes not in self._tf:
            b = C.candles(self.df1, minutes)
            b["st"], b["dir"] = C.supertrend(b, 10, 3.0)
            b["adx"] = C.adx(b, 14)
            b["flip"] = b["dir"] != b["dir"].shift()
            b["date"] = b.index.normalize()
            self._tf[minutes] = b
        return self._tf[minutes]

    def years_left(self, now64, expiry, model):
        """Vectorised time-to-expiry in years for an array of datetime64 'now' values."""
        exp_close = np.datetime64(expiry + pd.Timedelta(hours=15, minutes=30))
        if model == "calendar":
            return np.maximum((exp_close - now64).astype("timedelta64[s]").astype(float), 60) / (365 * 24 * 3600)
        # trading-time: minutes left today + 375 per full trading day until expiry, over 252*375
        day = pd.Timestamp(now64[0]).normalize()
        full_days = int(((self.td > day) & (self.td <= expiry)).sum())
        close_today = np.datetime64(day + pd.Timedelta(hours=15, minutes=30))
        left_today = np.maximum((close_today - now64).astype("timedelta64[s]").astype(float) / 60, 0)
        return np.maximum(left_today + 375 * full_days, 1) / (252 * 375)

    # ------------------------------------------------------------------------- backtest
    def run(self, tf_minutes, start, end, **over):
        cfg = {**CONFIG, **over}
        tf = self.tf(tf_minutes)
        htf = self.tf(cfg["htf_minutes"]) if cfg["htf_minutes"] else None
        if htf is not None:  # HTF direction known at each HTF candle end
            hdir = pd.Series(htf["dir"].values, index=pd.DatetimeIndex(htf["end"].values)).sort_index()
        days = self.td[(self.td >= pd.Timestamp(start)) & (self.td <= pd.Timestamp(end))]
        groups = {k: v for k, v in tf[(tf.date >= pd.Timestamp(start)) & (tf.date <= pd.Timestamp(end))].groupby("date")}
        lots, mpl, cap = cfg["lots"], cfg["margin_per_lot"], cfg["daily_cap"]
        trades, streak, skip = [], 0, False

        for day in days:
            if skip:
                skip, streak = False, 0
                continue
            if day not in groups or day not in self.m1 or np.isnan(self.d.loc[day, "iv"]):
                continue
            bars = groups[day]
            tm, mo, mh, ml, mc = self.m1[day]
            dd = self.d.loc[day]
            iv, lsz = dd.iv, C.lot_size(day)
            expiry = self.cal.pick(day) if cfg["expiry"] == "rule" else self.cal.expiries_from(day, 1)[0]
            day_open = mo[0]
            booked, n_tr, stopped, last_dir, last_entry_end, busy_until = 0.0, 0, False, None, None, None
            flips = []
            ends = bars["end"].values
            for j in range(len(bars)):
                c = bars.iloc[j]
                if c["flip"]:
                    flips.append((ends[j], int(c["dir"])))
                if stopped or n_tr >= cfg["max_trades"]:
                    continue
                if busy_until is not None and ends[j] < busy_until:
                    continue
                hm = pd.Timestamp(ends[j]).strftime("%H:%M")
                if not (cfg["window"][0] <= hm <= cfg["window"][1]):
                    continue
                if not flips or flips[-1][1] != int(c["dir"]) or c["adx"] <= cfg["adx_min"]:
                    continue
                if cfg["flip_candle_only"] and flips[-1][0] != ends[j]:
                    continue
                st_dir = int(c["dir"])
                pos_dir = st_dir if cfg["direction"] == "follow" else -st_dir
                if n_tr == 1 and not (st_dir != last_dir and flips[-1][0] > last_entry_end
                                      and cap + min(booked, 0) >= abs(cfg["init_stop"]) / 100 * mpl * lots):
                    continue
                s = float(c["Close"])
                if cfg["trend_filter_atr"] is not None and st_dir * (s - day_open) < cfg["trend_filter_atr"] * dd.atr14:
                    continue
                if htf is not None:
                    hd = hdir[hdir.index <= pd.Timestamp(ends[j])]
                    if len(hd) == 0 or int(hd.iat[-1]) != st_dir:
                        continue
                res = self._trade(cfg, day, tm, mo, mh, ml, mc, bars, j, s, pos_dir, st_dir, expiry, iv, lsz, booked)
                res.update(date=day.date(), trade_no=n_tr + 1, adx=round(float(c["adx"]), 1), timeframe=f"{tf_minutes}m",
                           lot_size=lsz, lots=lots, expiry=expiry.date())
                trades.append(res)
                booked += res["net_pnl"]
                n_tr += 1
                last_dir, last_entry_end = st_dir, ends[j]
                busy_until = np.datetime64(res["_exit_ts"])
                if res["exit_reason"].startswith("daily loss cap"):
                    stopped = True
            if n_tr:
                streak = streak + 1 if booked < 0 else 0
                if cfg["skip_after_losing_days"] and streak >= cfg["skip_after_losing_days"]:
                    skip = True
        out = pd.DataFrame(trades)
        return out.drop(columns=["_exit_ts"]) if len(out) else out

    def _trade(self, cfg, day, tm, mo, mh, ml, mc, bars, j, s, pos_dir, st_dir, expiry, iv, lsz, booked_before):
        lots, mpl, cap = cfg["lots"], cfg["margin_per_lot"], cfg["daily_cap"]
        entry_ts = bars["end"].values[j]
        if pos_dir == 1:
            kind = "P"
            short_k = math.floor((s - cfg["short_offset"]) / C.STRIKE_STEP) * C.STRIKE_STEP
            long_k = short_k - cfg["width"]
        else:
            kind = "C"
            short_k = math.ceil((s + cfg["short_offset"]) / C.STRIKE_STEP) * C.STRIKE_STEP
            long_k = short_k + cfg["width"]
        vs, vl = C.iv_for(short_k, s, iv, kind), C.iv_for(long_k, s, iv, kind)

        def val(spot, now64):
            t = self.years_left(np.atleast_1d(now64), expiry, cfg["time_model"])
            return _bs(spot, short_k, t, vs, kind), _bs(spot, long_k, t, vl, kind)

        ps0, pl0 = (float(x[0]) for x in val(np.array([s]), entry_ts))
        buy_l, sell_s = pl0 + C.SLIPPAGE_PTS, max(ps0 - C.SLIPPAGE_PTS, 0.05)
        credit = sell_s - buy_l
        qty = lots * lsz
        entry_ch = C.charges(day, buy_l * qty, sell_s * qty, 2)

        # ---- the window of minutes this trade can live in
        sq_ts = np.datetime64(day + pd.Timedelta(hours=int(cfg["square_off"][:2]), minutes=int(cfg["square_off"][3:])))
        st_exit_ts, st_exit_px = None, None
        if cfg["st_exit"] and cfg["direction"] == "follow":
            later = bars.iloc[j + 1:]
            against = later[later["dir"] != st_dir]
            if len(against):
                st_exit_ts, st_exit_px = against["end"].values[0], float(against["Close"].iat[0])
        limit = sq_ts if st_exit_ts is None or st_exit_ts >= sq_ts else st_exit_ts
        sel = (tm >= entry_ts) & (tm < limit)
        T, O, H, L, Cl = tm[sel], mo[sel], mh[sel], ml[sel], mc[sel]

        def pnl_lot(spot, now64):
            a, b = val(spot, now64)
            return (credit - (a - b)) * lsz

        rows = []  # (lots, spot, ts, reason)

        def book(n, spot, ts, reason):
            rows.append((n, float(spot), ts, reason))

        exit_done = False
        if len(T):
            now = T + np.timedelta64(1, "m")
            adv = L if pos_dir == 1 else H
            p_open, p_adv, p_close = pnl_lot(O, now), pnl_lot(adv, now), pnl_lot(Cl, now)
            pct_close = p_close / mpl * 100
            peak_prev = np.concatenate([[-99.0], np.maximum.accumulate(pct_close)[:-1]])
            stop_pct = _stop_ladder(peak_prev, cfg["init_stop"]) if cfg["stop"] == "ladder" else np.full(len(T), -1e9)
            stop_rs = stop_pct / 100 * mpl
            hit_stop = p_adv <= stop_rs
            part_idx = np.flatnonzero(pct_close >= cfg["partial_at"]) if cfg["partial_at"] else np.array([], int)
            ip = int(part_idx[0]) if len(part_idx) else 10 ** 9
            # open lots per minute (stop / cap checks happen before the partial at minute ip's close)
            lots_open = np.where(np.arange(len(T)) <= ip, lots, 1)
            booked_part = np.where(np.arange(len(T)) > ip, (lots - 1) * (p_close[min(ip, len(T) - 1)] if ip < len(T) else 0), 0)
            hit_cap = booked_before + booked_part + lots_open * p_adv <= -cap
            i_stop = int(np.argmax(hit_stop)) if hit_stop.any() else 10 ** 9
            i_cap = int(np.argmax(hit_cap)) if hit_cap.any() else 10 ** 9
            i_first = min(i_stop, i_cap)
            if lots == 1 and ip < i_first:  # 1 lot: +3% closes everything
                book(1, Cl[ip], now[ip], f"+{cfg['partial_at']:.0f}% profit booking")
                exit_done = True
            else:
                if ip < i_first:
                    book(lots - 1, Cl[ip], now[ip], f"+{cfg['partial_at']:.0f}% profit booking")
                if i_first < 10 ** 9:
                    i = i_first
                    n_open = int(lots_open[i])
                    if i_cap <= i_stop:
                        target = (-cap - booked_before - booked_part[i]) / n_open
                        reason = "daily loss cap Rs 5,000"
                    else:
                        target = stop_rs[i]
                        reason = "initial stop" if stop_pct[i] < 0 else f"trailing stop {stop_pct[i]:+.1f}%"
                    if p_open[i] <= target:
                        fill = O[i]
                    else:  # bisection between open (better) and adverse extreme (worse)
                        lo_s, hi_s = O[i], adv[i]
                        for _ in range(25):
                            mid = (lo_s + hi_s) / 2
                            if pnl_lot(np.array([mid]), now[i])[0] > target:
                                lo_s = mid
                            else:
                                hi_s = mid
                        fill = (lo_s + hi_s) / 2
                    book(n_open, fill, T[i], reason)
                    exit_done = True
        if not exit_done:
            n_open = lots - sum(r[0] for r in rows)
            if st_exit_ts is not None and st_exit_ts < sq_ts:
                book(n_open, st_exit_px, st_exit_ts, "candle closed beyond Supertrend")
            else:
                i_sq = np.flatnonzero(tm >= sq_ts)
                px = mo[i_sq[0]] if len(i_sq) else mc[-1]
                book(n_open, px, sq_ts, f"{cfg['square_off']} square-off")

        # ---- book every exit with slippage and charges
        gross, ch = 0.0, entry_ch
        for n, spot, ts, _ in rows:
            a, b = (float(x[0]) for x in val(np.array([spot]), np.datetime64(ts)))
            buy_back, sell_out = a + C.SLIPPAGE_PTS, max(b - C.SLIPPAGE_PTS, 0.05)
            q = n * lsz
            gross += (credit - (buy_back - sell_out)) * q
            ch += C.charges(day, buy_back * q, sell_out * q, 2)
        net = gross - ch
        word = "Bullish" if pos_dir == 1 else "Bearish"
        last = rows[-1]
        return dict(
            direction=word, strategy="Bull Put Spread" if pos_dir == 1 else "Bear Call Spread",
            entry_time=pd.Timestamp(entry_ts).strftime("%H:%M"), entry_spot=round(s, 1),
            short_strike=int(short_k), long_strike=int(long_k), option_type=kind + "E", net_credit=round(credit, 2),
            exit_time=pd.Timestamp(last[2]).strftime("%H:%M"), exit_spot=round(last[1], 1), exit_reason=last[3],
            gross_pnl=round(gross), charges=round(ch), net_pnl=round(net), result="WIN" if net > 0 else "LOSS",
            comment=(f"{word}: Supertrend flipped {'red->green' if st_dir == 1 else 'green->red'}"
                     f"{' (faded)' if cfg['direction'] == 'fade' else ''}; sold {short_k}{kind}E / bought {long_k}{kind}E, "
                     f"credit {credit:.1f}. Exits: " + "; ".join(f"{n} lot(s) {pd.Timestamp(ts):%H:%M} spot {sp:.0f} ({r})" for n, sp, ts, r in rows)),
            _exit_ts=pd.Timestamp(last[2]))
