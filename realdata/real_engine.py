"""
Backtest engine that uses REAL traded option prices instead of Black-Scholes.

Signals (Supertrend / ADX / 1-hour filter / window / trade-2 rules / skip-day rule) are computed
from NIFTY spot exactly as in bt/cs_lab.py. Only the trade P&L changes:
  * Entry at the signal candle's close time E: buy the hedge at the OPEN of minute E (first real
    price after the signal) + slippage, then sell the short leg at its open - slippage.
  * Every minute: position MTM = (credit - (short close - long close)) x quantity.
    Stop / lock / trail / target / daily cap are checked on these REAL minute closes, and the exit is
    filled at the NEXT minute's real open (+/- slippage) - what a live trader acting on a close gets.
  * Minutes with no trade in a leg (illiquid) carry the last traded price forward.
  * If a leg has no data at all that day, the trade is skipped and logged (no made-up prices).
"""
import math

import numpy as np
import pandas as pd

from bt import common as C
from bt.cs_lab import Lab


class RealLab(Lab):
    def __init__(self, df1, option_source):
        """option_source(day, expiry, strike, right) -> 1-minute DataFrame (Open/High/Low/Close) or empty."""
        super().__init__(df1)
        self.src = option_source
        self.missing = []

    def _leg(self, day, expiry, strike, right):
        df = self.src(day, expiry, strike, right)
        if df is None or len(df) == 0:
            return None
        grid = pd.date_range(day + pd.Timedelta(hours=9, minutes=15), day + pd.Timedelta(hours=15, minutes=29), freq="1min")
        return df[["Open", "Close"]].reindex(grid).ffill().bfill()

    def _trade_rupee(self, cfg, day, tm, mo, mh, ml, mc, bars, j, s, pos_dir, st_dir, expiry, iv, lsz, booked_before):
        lots, cap = cfg["lots"], cfg["daily_cap"]
        entry_ts = pd.Timestamp(bars["end"].values[j])
        if pos_dir == 1:
            kind, short_k = "PE", math.floor((s - cfg["short_offset"]) / C.STRIKE_STEP) * C.STRIKE_STEP
            long_k = short_k - cfg["width"]
        else:
            kind, short_k = "CE", math.ceil((s + cfg["short_offset"]) / C.STRIKE_STEP) * C.STRIKE_STEP
            long_k = short_k + cfg["width"]
        sh, lg = self._leg(day, expiry, short_k, kind), self._leg(day, expiry, long_k, kind)
        word = "Bullish" if pos_dir == 1 else "Bearish"
        if sh is None or lg is None:
            self.missing.append(dict(date=day.date(), entry_time=entry_ts.strftime("%H:%M"), direction=word,
                                     short=f"{short_k}{kind}", long=f"{long_k}{kind}", expiry=expiry.date(),
                                     missing="short" if sh is None else "long"))
            return dict(_skip=True, _exit_ts=entry_ts)
        slip = C.SLIPPAGE_PTS
        sq_ts = day + pd.Timedelta(hours=int(cfg["square_off"][:2]), minutes=int(cfg["square_off"][3:]))
        live = sh.index[(sh.index >= entry_ts) & (sh.index <= sq_ts)]
        if len(live) < 2:
            return dict(_skip=True, _exit_ts=entry_ts)
        e0 = live[0]
        buy_l, sell_s = lg.at[e0, "Open"] + slip, max(sh.at[e0, "Open"] - slip, 0.05)
        credit = sell_s - buy_l
        qty = lots * lsz
        entry_ch = C.charges(day, buy_l * qty, sell_s * qty, 2)
        mtm = (credit - (sh.loc[live, "Close"].values - lg.loc[live, "Close"].values)) * qty  # whole position, Rs

        peak, exit_i, reason = -1e18, None, None
        for i, m in enumerate(mtm[:-1]):            # last bar of the window is the square-off bar
            if peak < cfg["lock_trigger"]:
                stop = -cfg["sl_total"]
            elif cfg["trail_mode"] == "incremental":
                stop = cfg["lock_level"] + cfg["trail_frac"] * (peak - cfg["lock_trigger"])
            else:
                stop = max(cfg["lock_level"], cfg["trail_frac"] * peak)
            if booked_before + m <= -cap:
                exit_i, reason = i + 1, "daily loss cap"
            elif m <= stop:
                exit_i, reason = i + 1, ("stop loss -Rs %d" % cfg["sl_total"]) if stop < 0 else ("trailing stop locked +Rs %d" % stop)
            elif cfg["final_total"] and m >= cfg["final_total"]:
                exit_i, reason = i + 1, "target Rs %d reached" % cfg["final_total"]
            if exit_i is not None:
                break
            peak = max(peak, m)
        st_exit_ts = None
        if cfg["st_exit"]:
            later = bars.iloc[j + 1:]
            against = later[later["dir"] != st_dir]
            if len(against) and pd.Timestamp(against["end"].values[0]) <= sq_ts:
                st_exit_ts = pd.Timestamp(against["end"].values[0])
        if st_exit_ts is not None and (exit_i is None or live[exit_i] > st_exit_ts):
            exit_i, reason = int(np.searchsorted(live, st_exit_ts)), "candle closed beyond Supertrend"
        if exit_i is None:
            exit_i, reason = len(live) - 1, f"{cfg['square_off']} square-off"
        xt = live[min(exit_i, len(live) - 1)]
        buy_back, sell_out = sh.at[xt, "Open"] + slip, max(lg.at[xt, "Open"] - slip, 0.05)
        gross = (credit - (buy_back - sell_out)) * qty
        ch = entry_ch + C.charges(day, buy_back * qty, sell_out * qty, 2)
        net = gross - ch
        spot_at = dict(zip(pd.DatetimeIndex(tm), mo))
        return dict(
            direction=word, strategy="Bull Put Spread" if pos_dir == 1 else "Bear Call Spread",
            entry_time=e0.strftime("%H:%M"), entry_spot=round(s, 1), short_strike=int(short_k), long_strike=int(long_k),
            option_type=kind, short_entry=round(sh.at[e0, "Open"], 2), long_entry=round(lg.at[e0, "Open"], 2),
            net_credit=round(credit, 2), exit_time=xt.strftime("%H:%M"), exit_spot=round(spot_at.get(xt, np.nan), 1),
            short_exit=round(sh.at[xt, "Open"], 2), long_exit=round(lg.at[xt, "Open"], 2), exit_reason=reason,
            peak_mtm=round(max(peak, mtm[0])), gross_pnl=round(gross), charges=round(ch), net_pnl=round(net),
            result="WIN" if net > 0 else "LOSS", data="REAL traded prices",
            comment=(f"{word}: Supertrend flipped {'red->green' if st_dir == 1 else 'green->red'} (candle closed {entry_ts:%H:%M}). "
                     f"Sold {short_k}{kind} @ {sell_s:.2f}, bought {long_k}{kind} @ {buy_l:.2f} (exp {expiry:%d-%b-%y}), "
                     f"net credit {credit:.2f}. Exit {xt:%H:%M}: bought back short @ {buy_back:.2f}, sold hedge @ {sell_out:.2f} ({reason})."),
            _exit_ts=xt)

    def run(self, *a, **k):
        out = super().run(*a, **k)
        if len(out) and "_skip" in out:
            out = out[out["_skip"] != True].drop(columns=["_skip"])  # noqa: E712
        return out


def candidate_legs(lab, tf_minutes, start, end, cfg):
    """Every option leg the strategy COULD need: all candle closes meeting the entry conditions
    (ignoring trade-count / P&L rules, which only remove trades). Used to know what to download."""
    from bt.cs_lab import CONFIG
    cfg = {**CONFIG, **cfg}
    tf = lab.tf(tf_minutes, cfg["st_period"], cfg["st_mult"], cfg["adx_period"])
    htf = lab.tf(cfg["htf_minutes"], cfg["st_period"], cfg["st_mult"], 14) if cfg["htf_minutes"] else None
    hdir = pd.Series(htf["dir"].values, index=pd.DatetimeIndex(htf["end"].values)).sort_index() if htf is not None else None
    sub = tf[(tf.date >= pd.Timestamp(start)) & (tf.date <= pd.Timestamp(end))]
    legs = set()
    for day, bars in sub.groupby("date"):
        expiry = lab.cal.expiries_from(day, 2)[1] if cfg["expiry"] == "next" else lab.cal.pick(day)
        last_flip = None
        for _, c in bars.iterrows():
            if c["flip"]:
                last_flip = int(c["dir"])
            hm = pd.Timestamp(c["end"]).strftime("%H:%M")
            if not (cfg["window"][0] <= hm <= cfg["window"][1]) or last_flip != int(c["dir"]) or c["adx"] <= cfg["adx_min"]:
                continue
            if hdir is not None:
                hd = hdir[hdir.index <= pd.Timestamp(c["end"])]
                if len(hd) == 0 or int(hd.iat[-1]) != int(c["dir"]):
                    continue
            s, d = float(c["Close"]), int(c["dir"])
            if d == 1:
                k = math.floor((s - cfg["short_offset"]) / 50) * 50
                legs |= {(day, expiry, k, "PE"), (day, expiry, k - cfg["width"], "PE")}
            else:
                k = math.ceil((s + cfg["short_offset"]) / 50) * 50
                legs |= {(day, expiry, k, "CE"), (day, expiry, k + cfg["width"], "CE")}
    return sorted(legs)
