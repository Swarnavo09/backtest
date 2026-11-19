"""Which time convention matches real Nifty option prices: calendar time or trading time?

For each day: take real closing prices of near-ATM weekly options on day d-1, back out
implied vol under each convention, then predict that option's price at day d OPEN and
CLOSE (using actual Nifty open/close). Compare with the real open/close from bhavcopy.

    python calibrate.py
"""
import math
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import bs_price

ROOT = Path(__file__).parent
TRADE_MIN = 375                    # 09:15-15:30
YEAR_TRADE_MIN = 252 * TRADE_MIN


def implied_vol(price, S, K, T, kind):
    lo, hi = 0.01, 3.0
    intrinsic = max(0.0, S - K) if kind == "C" else max(0.0, K - S)
    if price <= intrinsic + 0.05 or T <= 0:
        return np.nan
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, mid, kind) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


class Clock:
    """Year fractions to expiry in calendar time or trading time."""

    def __init__(self, trading_days):
        self.days = sorted(trading_days)
        self.idx = {d: i for i, d in enumerate(self.days)}

    def cal(self, ts: datetime, expiry) -> float:
        e = datetime.combine(expiry, time(15, 30))
        return max((e - ts).total_seconds(), 60) / (365 * 86400)

    def trade(self, ts: datetime, expiry) -> float:
        d = ts.date()
        mins_today = max(0, (datetime.combine(d, time(15, 30)) - max(ts, datetime.combine(d, time(9, 15)))).total_seconds() / 60)
        if d == expiry:
            return max(mins_today, 1) / YEAR_TRADE_MIN
        full = sum(1 for x in self.days if d < x <= expiry)
        if expiry > self.days[-1]:      # beyond data: count weekdays
            full += np.busday_count(self.days[-1] + timedelta(days=1), expiry + timedelta(days=1))
        return (mins_today + full * TRADE_MIN) / YEAR_TRADE_MIN


def main():
    opt = pd.read_csv(ROOT / "data" / "nifty_opt_bhav.csv.gz", parse_dates=["date", "expiry"])
    n5 = pd.read_csv(ROOT / "data" / "nifty_5m_5y.csv", index_col=0, parse_dates=True)
    n5.index = pd.to_datetime(n5.index, utc=True).tz_convert("Asia/Kolkata")
    day = n5.groupby(n5.index.date).agg(o=("Open", "first"), c=("Close", "last"))
    clock = Clock(list(day.index))
    vx = pd.read_csv(ROOT / "data" / "indiavix_5m_5y.csv", index_col=0, parse_dates=True)
    vx.index = pd.to_datetime(vx.index, utc=True).tz_convert("Asia/Kolkata")
    vday = vx.groupby(vx.index.date).agg(o=("Open", "first"), c=("Close", "last"))
    dates = list(day.index)
    rows = []
    for i in range(1, len(dates)):
        d, dp = dates[i], dates[i - 1]
        today = opt[opt.date == pd.Timestamp(d)]
        prev = opt[opt.date == pd.Timestamp(dp)]
        if today.empty or prev.empty:
            continue
        exp = today.expiry.min().date()       # includes expiry day itself (0 DTE)
        S_prev, S_open, S_close = day.c[dp], day.o[d], day.c[d]
        atm = round(S_open / 50) * 50
        for kind, off in [("C", 0), ("P", 0), ("C", 100), ("P", -100), ("C", 200), ("P", -200)]:
            K = atm + off
            a = today[(today.expiry.dt.date == exp) & (today.strike == K) & (today.type == kind + "E")]
            b = prev[(prev.expiry.dt.date == exp) & (prev.strike == K) & (prev.type == kind + "E")]
            if a.empty or b.empty or a.volume.iloc[0] < 1000:
                continue
            p_prev, p_open, p_close = b.close.iloc[0], a.open.iloc[0], a.close.iloc[0]
            t_prev = datetime.combine(dp, time(15, 30))
            t_open, t_close = datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30))
            r = dict(date=d, dte=(exp - d).days, kind=kind, off=abs(off), K=K, real_open=p_open, real_close=p_close)
            convs = [("cal", clock.cal), ("trd", clock.trade)] + [
                (f"mix{int(w * 100)}", (lambda w: lambda t, e: w * clock.trade(t, e) + (1 - w) * clock.cal(t, e))(w))
                for w in (0.6, 0.7, 0.8, 0.9)]
            if dp not in vday.index or d not in vday.index:
                continue
            ro, rc = vday.o[d] / vday.c[dp], vday.c[d] / vday.c[dp]     # VIX moves since yesterday's close
            for conv, f in convs:
                iv = implied_vol(p_prev, S_prev, K, f(t_prev, exp), kind)
                if np.isnan(iv):
                    break
                r[f"{conv}_iv"] = iv
                r[f"{conv}_open"] = bs_price(S_open, K, f(t_open, exp), iv, kind)
                r[f"{conv}_close"] = bs_price(S_close, K, f(t_close, exp), iv, kind)
                r[f"{conv}v_open"] = bs_price(S_open, K, f(t_open, exp), iv * ro, kind)
                r[f"{conv}v_close"] = bs_price(S_close, K, f(t_close, exp), iv * rc, kind)
                # model change from open to close vs real change
            else:
                rows.append(r)
    x = pd.DataFrame(rows)
    x.to_csv(ROOT / "results" / "calibration.csv", index=False)
    convs = ["cal", "trd", "mix60", "mix70", "mix80", "mix90", "calv", "trdv", "mix60v", "mix70v", "mix80v", "mix90v"]
    for conv in convs:
        x[f"{conv}_err_open"] = x[f"{conv}_open"] - x.real_open
        x[f"{conv}_err_intraday"] = (x[f"{conv}_close"] - x[f"{conv}_open"]) - (x.real_close - x.real_open)
    x["spread_key"] = x.date.astype(str) + x.kind
    print(len(x), "option-days")
    print("mean intraday error (model change - real change), points per option per full session")
    x["bucket"] = np.where(x.dte == 0, "0 (expiry day)", np.where(x.dte <= 2, "1-2", "3+"))
    print(x.groupby(["bucket", "off"])[[f"{c}_err_intraday" for c in convs]].mean().round(2))
    print("mean opening error (model - real):")
    print(x.groupby("bucket")[[f"{c}_err_open" for c in convs]].mean().round(2))
    print("MAE intraday:", {c: round(x[f"{c}_err_intraday"].abs().mean(), 2) for c in convs})


if __name__ == "__main__":
    main()
