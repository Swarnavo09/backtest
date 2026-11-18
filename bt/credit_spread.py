"""
Supertrend(10,3) + ADX(14) intraday NIFTY credit-spread strategy (the user's rules).

Rules implemented (timeframe = 5 / 10 / 15 minute candles):
  Skip day      : if the last 3 trading days that had trades all ended in a net loss, skip the
                  next trading day (day 4), resume on day 5 (streak resets).
  Entry         : checked only at candle close, 09:25 <= close time <= 14:00, all of:
                    1. Supertrend flipped colour today (the current colour was set by a flip today)
                    2. candle closes on the correct side of the Supertrend line
                    3. ADX(14) > 20
                  red->green  => BULLISH => Bull Put Spread : sell put 100-150 pts below spot,
                                                              buy put 500 pts below the short put
                  green->red  => BEARISH => Bear Call Spread: sell call 100-150 pts above spot,
                                                              buy call 500 pts above the short call
  Expiry        : nearest weekly expiry if >= 5 calendar days away, else the next one
                  (= "Wed/Thu this week, Fri-Tue next week" for Tuesday expiries).
  Max 2 trades  : trade 2 only after trade 1 is closed, on a NEW flip in the OPPOSITE direction,
                  before 14:00, ADX > 20, and only if (5000 + today's booked P&L) >= full 1.5% stop.
  Stop / trail  : % of margin (Rs 40,000 per lot) on combined MTM of both legs.
                  start -1.5%; peak +1.5% -> +0.5%; +2% -> +1%; then stop = floor(peak) - 1%.
  Partial       : at +3%: 1 lot -> close all; >=2 lots -> close all but 1, runner keeps trailing.
  Exits         : first of stop/trail, candle CLOSE beyond Supertrend (opposite colour),
                  daily loss (booked + open) reaches Rs 5,000 (close all, stop for the day), 15:15.

Simulation: entries/Supertrend exits on candle closes; stops, trail, partials and the daily
cap are checked every 1-minute bar using the option-spread value re-priced from spot
(adverse extreme of the minute for stops, minute close for peak/partials).
"""
import math

import numpy as np
import pandas as pd

from bt import common as C

MARGIN_PER_LOT = 40_000
DAILY_CAP = 5_000
ADX_MIN = 20
SPREAD_WIDTH = 500


def _stop_level(peak):
    """Trailing-stop ladder (in % of margin) as a function of the best % reached so far."""
    if peak < 1.5:
        return -1.5
    if peak < 2.0:
        return 0.5
    return math.floor(peak) - 1.0


def run(df1, tf_minutes, start, end, lots=4, flip_candle_only=False):
    tf = C.candles(df1, tf_minutes)
    line, dirn = C.supertrend(tf, 10, 3.0)
    tf["st"], tf["dir"], tf["adx"] = line, dirn, C.adx(tf, 14)
    tf["flip"] = tf["dir"] != tf["dir"].shift()
    tf["date"] = tf.index.normalize()
    d = C.daily(df1)
    cal = C.ExpiryCalendar(d.index)

    days = [x for x in d.index if pd.Timestamp(start) <= x <= pd.Timestamp(end)]
    m1_by_day = {k: v for k, v in df1[df1.index >= pd.Timestamp(start)].groupby(df1[df1.index >= pd.Timestamp(start)].index.normalize())}
    tf_pos = {k: np.flatnonzero(tf["date"].values == np.datetime64(k)) for k in days}

    trades, day_log = [], []
    losing_streak, skip_next = 0, False
    stop_rupees_per_lot = 0.015 * MARGIN_PER_LOT

    for day in days:
        if skip_next:
            day_log.append(dict(date=day, status="SKIPPED (3 losing days in a row)", trades=0, net=0.0))
            skip_next, losing_streak = False, 0
            continue
        m1 = m1_by_day.get(day)
        idx = tf_pos[day]
        if m1 is None or len(idx) == 0 or np.isnan(d.loc[day, "iv"]):
            continue
        atm_iv = d.loc[day, "iv"]
        lsz = C.lot_size(day)
        expiry = cal.pick(day)

        day_booked, n_trades, day_stopped = 0.0, 0, False
        last_trade_dir, last_entry_i = None, None
        pos = None  # open position dict
        # candle-close events, processed in time order (robust to a missing 1-min bar)
        ev_times = list(tf["end"].values[idx])
        ev_ptr = 0

        def mtm_per_lot(spot, now):
            v = C.spread_value(spot, now, pos["expiry"], pos["short_k"], pos["long_k"], pos["kind"], atm_iv, pos["ref"])
            return (pos["credit"] - v) * lsz  # rupees per lot, before exit slippage/charges

        def close_lots(n, spot, now, reason):
            """Close n lots at a given spot; books P&L incl. exit slippage and charges."""
            nonlocal day_booked
            t = C.years_to_expiry(now, pos["expiry"])
            ps = float(C.bs_price(spot, pos["short_k"], t, C.iv_for(pos["short_k"], pos["ref"], atm_iv, pos["kind"]), pos["kind"]))
            pl = float(C.bs_price(spot, pos["long_k"], t, C.iv_for(pos["long_k"], pos["ref"], atm_iv, pos["kind"]), pos["kind"]))
            buy_back = ps + C.SLIPPAGE_PTS        # buy back the sold leg first
            sell_out = max(pl - C.SLIPPAGE_PTS, 0.05)  # then sell the protective leg
            qty = n * lsz
            gross = (pos["credit"] - (buy_back - sell_out)) * qty
            ch = C.charges(day, buy_back * qty, sell_out * qty, 2) + pos["entry_charges"] * n / pos["lots0"]
            pos["gross"] += gross
            pos["charges"] += ch
            pos["lots"] -= n
            day_booked += gross - ch
            pos["exits"].append(f"{n} lot(s) @ {now:%H:%M} spot {spot:.0f} ({reason})")
            if pos["lots"] == 0:
                pos["exit_time"], pos["exit_spot"], pos["reason"] = now, spot, reason

        def finish():
            nonlocal pos
            net = pos["gross"] - pos["charges"]
            dir_word = "Bullish" if pos["dir"] == 1 else "Bearish"
            comment = (f"{dir_word}: Supertrend flipped {'red->green' if pos['dir'] == 1 else 'green->red'} "
                       f"(candle closed {pos['entry_time']:%H:%M}), ADX {pos['adx']:.1f} > 20. "
                       f"Sold {pos['short_k']:.0f}{pos['kind']}E / bought {pos['long_k']:.0f}{pos['kind']}E "
                       f"exp {pos['expiry']:%d-%b-%y} for net credit {pos['credit']:.1f}. "
                       f"Peak MTM {pos['peak']:+.2f}% of margin. Exits: " + "; ".join(pos["exits"]) + ".")
            trades.append(dict(
                date=day.date(), timeframe=f"{tf_minutes}m", trade_no=pos["no"], direction=dir_word,
                strategy="Bull Put Spread" if pos["dir"] == 1 else "Bear Call Spread",
                entry_time=pos["entry_time"].strftime("%H:%M"), entry_spot=round(pos["spot"], 1),
                adx=round(pos["adx"], 1), expiry=pos["expiry"].date(),
                short_strike=int(pos["short_k"]), long_strike=int(pos["long_k"]), option_type=pos["kind"] + "E",
                lots=pos["lots0"], lot_size=lsz, qty=pos["lots0"] * lsz, net_credit=round(pos["credit"], 2),
                exit_time=pos["exit_time"].strftime("%H:%M"), exit_spot=round(pos["exit_spot"], 1),
                exit_reason=pos["reason"], peak_pct=round(pos["peak"], 2),
                gross_pnl=round(pos["gross"], 0), charges=round(pos["charges"], 0), net_pnl=round(net, 0),
                result="WIN" if net > 0 else "LOSS", comment=comment))
            pos = None

        flips_today = []  # (candle index, new direction)
        for t, bar in m1.iterrows():
            # ---------------- candle-close events happen at the START of minute t
            entered = False
            while ev_ptr < len(idx) and pd.Timestamp(ev_times[ev_ptr]) <= t:
                i = idx[ev_ptr]
                ev_ptr += 1
                c = tf.iloc[i]
                if c["flip"]:
                    flips_today.append((i, int(c["dir"])))
                # exit: candle closed beyond Supertrend (colour now against us)
                if pos is not None and int(c["dir"]) != pos["dir"]:
                    close_lots(pos["lots"], c["Close"], t, "candle closed beyond Supertrend")
                    finish()
                # entry check
                hm = t.strftime("%H:%M")
                if (pos is None and not day_stopped and n_trades < 2 and "09:25" <= hm <= "14:00"
                        and flips_today and flips_today[-1][1] == int(c["dir"])
                        and c["adx"] > ADX_MIN
                        and ((c["dir"] == 1 and c["Close"] > c["st"]) or (c["dir"] == -1 and c["Close"] < c["st"]))):
                    flip_i = flips_today[-1][0]
                    ok = True
                    if flip_candle_only and flip_i != i:
                        ok = False
                    if n_trades == 1:  # trade-2 conditions
                        ok = ok and int(c["dir"]) != last_trade_dir and flip_i > last_entry_i \
                            and (DAILY_CAP + min(day_booked, 0)) >= stop_rupees_per_lot * lots
                    if ok:
                        s = c["Close"]
                        dirc = int(c["dir"])
                        if dirc == 1:
                            kind, short_k = "P", math.floor((s - 100) / C.STRIKE_STEP) * C.STRIKE_STEP
                            long_k = short_k - SPREAD_WIDTH
                        else:
                            kind, short_k = "C", math.ceil((s + 100) / C.STRIKE_STEP) * C.STRIKE_STEP
                            long_k = short_k + SPREAD_WIDTH
                        tt = C.years_to_expiry(t, expiry)
                        pl = float(C.bs_price(s, long_k, tt, C.iv_for(long_k, s, atm_iv, kind), kind)) + C.SLIPPAGE_PTS  # buy hedge first
                        ps = max(float(C.bs_price(s, short_k, tt, C.iv_for(short_k, s, atm_iv, kind), kind)) - C.SLIPPAGE_PTS, 0.05)
                        qty = lots * lsz
                        pos = dict(no=n_trades + 1, dir=dirc, kind=kind, short_k=short_k, long_k=long_k, expiry=expiry,
                                   ref=s, spot=s, credit=ps - pl, adx=c["adx"], entry_time=t, lots=lots, lots0=lots,
                                   entry_charges=C.charges(day, pl * qty, ps * qty, 2), gross=0.0, charges=0.0,
                                   peak=-99.0, partial=False, exits=[])
                        n_trades += 1
                        last_trade_dir, last_entry_i = dirc, i
                        entered = True
            if entered:
                continue  # a new position starts being managed from the next minute

            if pos is None:
                continue
            hm = t.strftime("%H:%M")
            # ---------------- 15:15 square-off
            if hm >= "15:15":
                close_lots(pos["lots"], bar.Open, t, "15:15 square-off")
                finish()
                continue
            now = t + pd.Timedelta(minutes=1)
            adv_spot = bar.Low if pos["dir"] == 1 else bar.High
            per_lot_open, per_lot_adv, per_lot_close = (mtm_per_lot(x, now) for x in (bar.Open, adv_spot, bar.Close))
            # ---------------- daily loss cap (booked + open, after estimated exit costs)
            if day_booked + per_lot_adv * pos["lots"] <= -DAILY_CAP:
                target = (-DAILY_CAP - day_booked) / pos["lots"]
                fill_spot = bar.Open if per_lot_open <= target else _solve_spot(mtm_per_lot, target, bar.Open, adv_spot, now)
                close_lots(pos["lots"], fill_spot, t, "daily loss cap Rs 5,000")
                finish()
                day_stopped = True
                continue
            # ---------------- stop / trailing stop
            stop_pct = _stop_level(pos["peak"])
            target = stop_pct / 100 * MARGIN_PER_LOT
            if per_lot_adv <= target:
                fill_spot = bar.Open if per_lot_open <= target else _solve_spot(mtm_per_lot, target, bar.Open, adv_spot, now)
                close_lots(pos["lots"], fill_spot, t, "initial stop -1.5%" if stop_pct < 0 else f"trailing stop {stop_pct:+.1f}%")
                finish()
                continue
            # ---------------- update peak and partial booking at +3%
            pct_close = per_lot_close / MARGIN_PER_LOT * 100
            pos["peak"] = max(pos["peak"], pct_close)
            if not pos["partial"] and pct_close >= 3.0:
                pos["partial"] = True
                n = pos["lots"] if pos["lots"] == 1 else pos["lots"] - 1
                close_lots(n, bar.Close, now, "+3% profit booking")
                if pos["lots"] == 0:
                    finish()
        if pos is not None:  # safety: data ended before 15:15
            close_lots(pos["lots"], m1.Close.iat[-1], m1.index[-1], "end of data")
            finish()

        day_net = sum(tr["net_pnl"] for tr in trades if tr["date"] == day.date())
        if n_trades:
            losing_streak = losing_streak + 1 if day_net < 0 else 0
            if losing_streak >= 3:
                skip_next = True
        day_log.append(dict(date=day, status="traded" if n_trades else "no signal", trades=n_trades, net=day_net))

    return pd.DataFrame(trades), pd.DataFrame(day_log)


def _solve_spot(f, target, s_good, s_bad, now, it=30):
    """Find spot between s_good (MTM above target) and s_bad (MTM below) where MTM == target."""
    lo, hi = s_good, s_bad
    for _ in range(it):
        mid = (lo + hi) / 2
        if f(mid, now) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
