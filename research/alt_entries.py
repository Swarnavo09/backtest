"""
Keep the user's CREDIT-SPREAD structure (sell 100 OTM, buy 500 further, 4 lots, Rs 5,000 daily cap)
but swap the Supertrend-flip ENTRY for signals that showed an edge in the earlier research:

  ALT-1  Setup A/B breakout direction -> credit spread (Bull Put on upside break, Bear Call on downside)
         exits from the playbook: spot stop (other side of OR / 0.25 ATR), 0.6 ATR trail, 15:15.
  ALT-2  Range-day iron condor: if the first hour (09:15-10:15) range <= 0.45 x ATR14, sell an iron condor
         at 10:15 with short strikes ~0.5 x ATR from spot and 500-pt wings; exit at 15:15, or when spot
         touches either short strike, or at the daily cap.
  COMBO  best filters on the Supertrend entry: 1-hour Supertrend agrees + 09:25-11:00 + ADX > 25.

DEV 2019-03..2023-11 / TEST last 3 years, same pricing + cost model as everything else.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

from bt import common as C, playbook_ab as AB
from bt.cs_lab import Lab, _bs
from research.refine_grid import DEV, TEST, stat

LOTS, CAP = 4, 5000


def leg_price(spot, k, now, expiry, iv, ref, kind):
    return float(_bs(np.array([spot]), k, np.array([C.years_to_expiry(now, expiry)]), C.iv_for(k, ref, iv, kind), kind)[0])


def credit_from_ab(df, d, cal, start, end):
    """Re-price the playbook A/B signals as credit spreads (same entry/exit times and spots)."""
    ab = AB.run(df, start, end, lots=LOTS)
    out = []
    for _, r in ab.iterrows():
        day = pd.Timestamp(r.date)
        iv, lsz, expiry = d.loc[day, "iv"], C.lot_size(day), cal.pick(day)
        s, side = r.entry_spot, 1 if r.direction == "Bullish" else -1
        kind = "P" if side > 0 else "C"
        sk = math.floor((s - 100) / 50) * 50 if side > 0 else math.ceil((s + 100) / 50) * 50
        lk = sk - 500 if side > 0 else sk + 500
        t_in = pd.Timestamp(f"{r.date} {r.entry_time}")
        t_out = pd.Timestamp(f"{r.date} {r.exit_time}") + pd.Timedelta(minutes=1)
        if t_out.strftime("%H:%M") > "15:15":
            t_out = day + pd.Timedelta(hours=15, minutes=15)
        sell_s = leg_price(s, sk, t_in, expiry, iv, s, kind) - C.SLIPPAGE_PTS
        buy_l = leg_price(s, lk, t_in, expiry, iv, s, kind) + C.SLIPPAGE_PTS
        bb = leg_price(r.exit_spot, sk, t_out, expiry, iv, s, kind) + C.SLIPPAGE_PTS
        so = max(leg_price(r.exit_spot, lk, t_out, expiry, iv, s, kind) - C.SLIPPAGE_PTS, 0.05)
        q = r.lots * lsz
        gross = ((sell_s - buy_l) - (bb - so)) * q
        ch = C.charges(day, (buy_l + bb) * q, (sell_s + so) * q, 4)
        out.append(dict(date=r.date, setup=r.setup, direction=r.direction,
                        strategy="Bull Put Spread" if side > 0 else "Bear Call Spread",
                        entry_time=r.entry_time, exit_time=r.exit_time, entry_spot=s, exit_spot=r.exit_spot,
                        short_strike=sk, long_strike=lk, lots=r.lots, gross_pnl=round(gross), charges=round(ch),
                        net_pnl=round(gross - ch), exit_reason=r.exit_reason))
    t = pd.DataFrame(out)
    # apply the Rs 5,000 daily cap approximately (cap the day's combined loss)
    return t


def iron_condor(df, d, cal, start, end, or_max=0.45, short_atr=0.5):
    out = []
    sub = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end) + pd.Timedelta(days=1))]
    for day, m in sub.groupby(sub.index.normalize()):
        if day not in d.index or np.isnan(d.loc[day, "atr14"]) or np.isnan(d.loc[day, "iv"]):
            continue
        atr, iv, lsz, expiry = d.loc[day, "atr14"], d.loc[day, "iv"], C.lot_size(day), cal.pick(day)
        fh = m[m.index < day + pd.Timedelta(hours=10, minutes=15)]
        rest = m[(m.index >= day + pd.Timedelta(hours=10, minutes=15)) & (m.index < day + pd.Timedelta(hours=15, minutes=15))]
        if len(rest) < 200 or fh.High.max() - fh.Low.min() > or_max * atr:
            continue
        s, t_in = rest.Open.iat[0], rest.index[0]
        pk = math.floor((s - short_atr * atr) / 50) * 50
        ck = math.ceil((s + short_atr * atr) / 50) * 50
        legs = [(pk, "P", -1), (pk - 500, "P", +1), (ck, "C", -1), (ck + 500, "C", +1)]  # -1 = sold
        fill_in = {k: leg_price(s, k, t_in, expiry, iv, s, kd) - sg * C.SLIPPAGE_PTS * -1 for k, kd, sg in legs}
        credit = sum(-sg * fill_in[k] for k, kd, sg in legs)
        q = LOTS * lsz
        exit_spot, t_out, reason = rest.Open.iat[-1], day + pd.Timedelta(hours=15, minutes=15), "15:15 square-off"
        for t, b in rest.iterrows():
            if b.Low <= pk or b.High >= ck:
                exit_spot, t_out, reason = (pk if b.Low <= pk else ck), t, "spot touched short strike"
                break
            if t.minute % 5 == 0:  # check daily cap every 5 minutes on close
                val = sum(-sg * leg_price(b.Close, k, t, expiry, iv, s, kd) for k, kd, sg in legs)
                if (credit - val) * q <= -CAP:
                    exit_spot, t_out, reason = b.Close, t, "daily loss cap Rs 5,000"
                    break
        fill_out = {k: leg_price(exit_spot, k, t_out, expiry, iv, s, kd) + sg * -1 * C.SLIPPAGE_PTS for k, kd, sg in legs}
        cost_to_close = sum(-sg * fill_out[k] for k, kd, sg in legs)
        gross = (credit - cost_to_close) * q
        buy_t = sum(fill_in[k] for k, kd, sg in legs if sg > 0) + sum(fill_out[k] for k, kd, sg in legs if sg < 0)
        sell_t = sum(fill_in[k] for k, kd, sg in legs if sg < 0) + sum(fill_out[k] for k, kd, sg in legs if sg > 0)
        ch = C.charges(day, buy_t * q, sell_t * q, 8)
        out.append(dict(date=day.date(), direction="Neutral", strategy="Iron Condor", entry_time="10:15",
                        entry_spot=round(s, 1), put_short=pk, call_short=ck, credit=round(credit, 1),
                        exit_time=pd.Timestamp(t_out).strftime("%H:%M"), exit_spot=round(exit_spot, 1),
                        exit_reason=reason, lots=LOTS, gross_pnl=round(gross), charges=round(ch), net_pnl=round(gross - ch)))
    return pd.DataFrame(out)


if __name__ == "__main__":
    df = C.load_1m()
    df = df[df.index >= "2018-09-01"]
    d, lab = C.daily(df), Lab(df)
    cal = C.ExpiryCalendar(d.index)
    res = {}
    for nm, fn in [("ALT-1 breakout -> credit spread", lambda a, b: credit_from_ab(df, d, cal, a, b)),
                   ("ALT-2 range-day iron condor", lambda a, b: iron_condor(df, d, cal, a, b))]:
        for per, (a, b) in (("dev", DEV), ("test", TEST)):
            res[(nm, per)] = fn(a, b)
    for m in (10, 15):
        for per, (a, b) in (("dev", DEV), ("test", TEST)):
            res[(f"COMBO ST-{m}m: 1h agrees + 09:25-11:00 + ADX>25", per)] = lab.run(
                m, a, b, htf_minutes=60, window=("09:25", "11:00"), adx_min=25)
    rows = []
    for (nm, per), t in res.items():
        s = stat(t)
        rows.append(dict(strategy=nm, period=per, trades=s["n"], win=round(s["win"], 1), pf=round(s["pf"], 2),
                         net=round(s["net"]), per_year=round(s.get("per_yr", 0))))
        t.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"alt_{nm.split()[0]}_{per}.csv".replace("/", "")), index=False)
    print(pd.DataFrame(rows).to_string(index=False))
