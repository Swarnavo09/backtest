"""
The PREVIOUS backtest (Nifty playbook from the earlier research), expressed in options so it
can be compared like-for-like with the credit-spread strategy.

  Setup A - narrow 30-min opening-range breakout
    OR = high/low of 09:15-09:45; trade only if OR width <= 0.35 x ATR14.
    Entry: first 5-min close beyond OR (until 12:00).  Stop: other side of OR.
  Setup B - previous-day high/low breakout
    Only if the day opens inside yesterday's range. Entry: first 5-min close above PDH / below
    PDL between 10:15 and 13:30.  Stop: 0.25 x ATR14 from entry.
  Both: trail 0.6 x ATR14 from the best spot price, exit 15:20. Decisions on SPOT.

Options expression (as recommended in the playbook):
  Bullish -> Bull Call debit spread: buy ATM CE, sell CE ~1 x ATR14 higher.
  Bearish -> Bear Put  debit spread: buy ATM PE, sell PE ~1 x ATR14 lower.
  4 lots per trade; if the other setup already has an open position, the new one uses 2 lots.
  Same expiry rule and same option-pricing/cost model as the credit-spread backtest.
"""
import math

import numpy as np
import pandas as pd

from bt import common as C

TRAIL_ATR = 0.6


def run(df1, start, end, lots=4):
    d = C.daily(df1)
    d["ph"], d["pl"] = d.High.shift(), d.Low.shift()
    cal = C.ExpiryCalendar(d.index)
    sub = df1[df1.index >= pd.Timestamp(start)]
    m1_by_day = {k: v for k, v in sub.groupby(sub.index.normalize())}
    c5 = C.candles(sub, 5)
    c5_by_day = {k: v for k, v in c5.groupby(c5.index.normalize())}
    trades = []

    for day, m1 in m1_by_day.items():
        if day > pd.Timestamp(end) or day not in d.index or np.isnan(d.loc[day, "atr14"]):
            continue
        dd, bars = d.loc[day], c5_by_day[day]
        atr, iv, lsz, expiry = dd.atr14, dd.iv, C.lot_size(day), cal.pick(day)
        signals = []
        # ---- Setup A
        orr = m1[m1.index < day + pd.Timedelta(hours=9, minutes=45)]
        hi, lo = orr.High.max(), orr.Low.min()
        if hi - lo <= 0.35 * atr:
            for t, b in bars.iterrows():
                hm = b["end"].strftime("%H:%M")
                if hm <= "09:45":
                    continue
                if hm > "12:00":
                    break
                side = 1 if b.Close > hi else (-1 if b.Close < lo else 0)
                if side:
                    signals.append(("A", b["end"], side, b.Close, lo if side > 0 else hi,
                                    f"30-min opening range {lo:.0f}-{hi:.0f} was narrow ({(hi - lo) / atr:.2f} x ATR); "
                                    f"5-min close {b.Close:.0f} broke {'above' if side > 0 else 'below'} it"))
                    break
        # ---- Setup B
        if dd.pl < bars.Open.iat[0] < dd.ph:
            for t, b in bars.iterrows():
                hm = t.strftime("%H:%M")
                if hm < "10:15":
                    continue
                if hm > "13:30":
                    break
                side = 1 if b.Close > dd.ph else (-1 if b.Close < dd.pl else 0)
                if side:
                    signals.append(("B", b["end"], side, b.Close, b.Close - side * 0.25 * atr,
                                    f"opened inside yesterday's range; 5-min close {b.Close:.0f} broke "
                                    f"{'above PDH ' + format(dd.ph, '.0f') if side > 0 else 'below PDL ' + format(dd.pl, '.0f')}"))
                    break
        signals.sort(key=lambda x: x[1])
        open_until = {}
        for setup, t_in, side, s_in, stop, why in signals:
            other_open = any(v > t_in for k, v in open_until.items() if k != setup)
            n_lots = lots // 2 if other_open else lots
            kind = "C" if side > 0 else "P"
            long_k = round(s_in / C.STRIKE_STEP) * C.STRIKE_STEP
            width = max(C.STRIKE_STEP * 2, round(atr / C.STRIKE_STEP) * C.STRIKE_STEP)
            short_k = long_k + side * width
            ref = s_in

            def price(spot, now, k):
                return float(C.bs_price(spot, k, C.years_to_expiry(now, expiry), C.iv_for(k, ref, iv, kind), kind))
            pay_long = price(s_in, t_in, long_k) + C.SLIPPAGE_PTS
            get_short = max(price(s_in, t_in, short_k) - C.SLIPPAGE_PTS, 0.05)
            debit = pay_long - get_short
            # ---- manage on spot, minute by minute
            best, exit_spot, exit_t, reason, init_stop = s_in, None, None, None, stop
            for t, b in m1[m1.index >= t_in].iterrows():
                if t.strftime("%H:%M") >= "15:20":
                    exit_spot, exit_t, reason = b.Open, t, "15:20 time exit"
                    break
                adverse = b.Low if side > 0 else b.High
                if (side > 0 and adverse <= stop) or (side < 0 and adverse >= stop):
                    gapped = (side > 0 and b.Open <= stop) or (side < 0 and b.Open >= stop)
                    exit_spot, exit_t = (b.Open if gapped else stop), t
                    reason = "initial stop" if stop == init_stop else "trailing stop 0.6 ATR"
                    break
                best = max(best, b.High) if side > 0 else min(best, b.Low)
                stop = max(stop, best - TRAIL_ATR * atr) if side > 0 else min(stop, best + TRAIL_ATR * atr)
            if exit_spot is None:
                exit_spot, exit_t, reason = m1.Close.iat[-1], m1.index[-1], "end of data"
            now = exit_t + pd.Timedelta(minutes=1)
            sell_long = max(price(exit_spot, now, long_k) - C.SLIPPAGE_PTS, 0.05)
            buy_short = price(exit_spot, now, short_k) + C.SLIPPAGE_PTS
            qty = n_lots * lsz
            gross = (sell_long - buy_short - debit) * qty
            ch = C.charges(day, (pay_long + buy_short) * qty, (get_short + sell_long) * qty, 4)
            net = gross - ch
            open_until[setup] = exit_t
            word = "Bullish" if side > 0 else "Bearish"
            strat = "Bull Call Debit Spread" if side > 0 else "Bear Put Debit Spread"
            trades.append(dict(
                date=day.date(), timeframe="5m", setup="A narrow ORB" if setup == "A" else "B PDH/PDL break",
                direction=word, strategy=strat, entry_time=t_in.strftime("%H:%M"), entry_spot=round(s_in, 1),
                expiry=expiry.date(), long_strike=int(long_k), short_strike=int(short_k), option_type=kind + "E",
                lots=n_lots, lot_size=lsz, qty=qty, net_debit=round(debit, 2),
                exit_time=exit_t.strftime("%H:%M"), exit_spot=round(exit_spot, 1), exit_reason=reason,
                spot_move_pts=round(side * (exit_spot - s_in), 1),
                gross_pnl=round(gross, 0), charges=round(ch, 0), net_pnl=round(net, 0),
                result="WIN" if net > 0 else "LOSS",
                comment=(f"{word}: Setup {setup} - {why} at {t_in:%H:%M}. Bought {long_k:.0f}{kind}E / sold "
                         f"{short_k:.0f}{kind}E exp {expiry:%d-%b-%y} for debit {debit:.1f}. "
                         f"Exit {exit_t:%H:%M} at spot {exit_spot:.0f} ({reason}), "
                         f"spot moved {side * (exit_spot - s_in):+.0f} pts in our favour.")))
    return pd.DataFrame(trades)
