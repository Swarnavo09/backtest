"""
Backtest the refined strategy (STRATEGY.md v2) on REAL NSE prices via ICICI Direct Breeze.

  pip install breeze-connect pandas numpy pyarrow openpyxl matplotlib
  set BREEZE_API_KEY=...   set BREEZE_API_SECRET=...   set BREEZE_SESSION_TOKEN=...   (Windows)
  python realdata/run_real.py --out "C:\\Users\\<you>\\Documents\\NiftyBacktest"

Steps: (1) download real 1-min NIFTY index for the last 2 years (+ warm-up),
(2) find every option leg the strategy could need, (3) download those legs' real 1-min candles,
(4) run the strategy on real prices, (5) write an Excel + summary into --out.
All downloads are cached in realdata/cache/, so a run interrupted by the daily API limit can
simply be re-run the next day (with a fresh session token) and continues where it stopped.

--mock runs the whole pipeline with MODEL prices instead of Breeze (only to test the plumbing).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run_refined  # noqa: E402,F401  (sets the refined v2 config on run_final)
import run_final as R  # noqa: E402
from bt import common as C  # noqa: E402
from realdata.real_engine import RealLab, candidate_legs  # noqa: E402

TF = 15


def weekly_and_yearly(t, start, end):
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"])
    w = R.weekly_table(t)
    w["ws"] = pd.to_datetime(w.week_start)
    y1 = start + pd.DateOffset(years=1)
    out = []
    for label, mt, mw in ((f"Year 1 ({start:%d-%b-%y} -> {y1 - pd.Timedelta(days=1):%d-%b-%y})", t.date < y1, w.ws < y1),
                          (f"Year 2 ({y1:%d-%b-%y} -> {end:%d-%b-%y})", t.date >= y1, w.ws >= y1)):
        tt, ww = t[mt], w[mw]
        if not len(tt):
            continue
        b, s = ww.loc[ww.net.idxmax()], ww.loc[ww.net.idxmin()]
        out.append(dict(period=label, trades=len(tt), win_pct=round((tt.net_pnl > 0).mean() * 100, 1), net=round(tt.net_pnl.sum()),
                        max_week_profit=round(b.net), week_of_max_profit=b.week_start, max_week_loss=round(s.net),
                        week_of_max_loss=s.week_start, bullish_net=round(tt.net_pnl[tt.direction == "Bullish"].sum()),
                        bearish_net=round(tt.net_pnl[tt.direction == "Bearish"].sum())))
    return w.drop(columns=["ws"]), pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--mock", action="store_true", help="model prices instead of Breeze (pipeline test only)")
    ap.add_argument("--spot", choices=["breeze", "local"], default="breeze",
                    help="breeze = real NSE index from Breeze; local = data/nifty_1m.parquet")
    a = ap.parse_args()
    end = pd.Timestamp(os.environ.get("BT_END", pd.Timestamp.today().normalize() - pd.Timedelta(days=1)))
    start = end - pd.DateOffset(years=a.years)
    warm = start - pd.DateOffset(months=4)
    os.makedirs(a.out, exist_ok=True)

    # ---------------- 1. spot
    br = None
    if not a.mock:
        from realdata.breeze_client import Breeze
        br = Breeze()
    if a.mock or a.spot == "local":
        spot = C.load_1m()
        spot = spot[spot.index >= warm]
        spot_src = "data/nifty_1m.parquet (public dataset)"
    else:
        days = pd.bdate_range(warm, end)
        frames = []
        for i, d in enumerate(days):
            f = br.spot_day(d)
            if len(f):
                frames.append(f[["Open", "High", "Low", "Close"]])
            if i % 50 == 0:
                print(f"spot {d:%Y-%m-%d}  ({i + 1}/{len(days)} days, API calls so far {br.calls})", flush=True)
        spot = pd.concat(frames).sort_index().between_time("09:15", "15:29")
        n = spot.groupby(spot.index.date).size()
        spot = spot[pd.Index(spot.index.date).isin(n[n >= 300].index)]
        spot_src = "ICICI Breeze - NSE NIFTY 50 index, 1-minute"
    print(f"spot: {spot.index[0]} -> {spot.index[-1]}, {spot.index.normalize().nunique()} days ({spot_src})")

    # ---------------- 2/3. option legs
    if a.mock:
        from realdata.mock_source import model_leg
        src = model_leg(spot)
    else:
        src = br.option_day
    lab = RealLab(spot, src)
    legs = candidate_legs(lab, TF, start, end, R.FINAL)
    print(f"option legs needed: {len(legs)} (one API call each, cached)")
    if not a.mock:
        for i, (d, e, k, r) in enumerate(legs):
            br.option_day(d, e, k, r)
            if i % 50 == 0:
                print(f"  legs {i + 1}/{len(legs)}  API calls so far {br.calls}", flush=True)

    # ---------------- 4. backtest on real prices
    t = lab.run(TF, start, end, **R.FINAL)
    if not len(t):
        raise SystemExit("No trades - check that data downloaded (see realdata/cache/).")
    t["date"] = pd.to_datetime(t["date"])
    w, yr = weekly_and_yearly(t, start, end)
    eq = t.groupby("date").net_pnl.sum().cumsum()
    wins, losses = t.net_pnl[t.net_pnl > 0], t.net_pnl[t.net_pnl <= 0]
    summ = pd.DataFrame({"metric": ["Data (options)", "Data (spot)", "Period", "Trades", "Win rate %", "Net P&L Rs", "Profit factor",
                                    "Avg win Rs", "Avg loss Rs", "Max drawdown Rs", "Trades skipped (no option data)"],
                         "value": ["MOCK model prices (pipeline test)" if a.mock else "REAL NSE traded prices (ICICI Breeze, 1-min)",
                                   spot_src, f"{start:%d-%b-%Y} -> {end:%d-%b-%Y}", len(t), round((t.net_pnl > 0).mean() * 100, 1),
                                   round(t.net_pnl.sum()), round(wins.sum() / max(-losses.sum(), 1), 2), round(wins.mean() if len(wins) else 0),
                                   round(losses.mean() if len(losses) else 0), round((eq - eq.cummax()).min()), len(lab.missing)]})
    tag = "MOCK" if a.mock else "REAL"
    xl = os.path.join(a.out, f"nifty_supertrend_backtest_{tag}_{start:%Y%m%d}_{end:%Y%m%d}.xlsx")
    with pd.ExcelWriter(xl) as xw:
        summ.to_excel(xw, sheet_name="Summary", index=False)
        yr.to_excel(xw, sheet_name="Yearly + best-worst week", index=False)
        t.assign(date=t.date.dt.date).to_excel(xw, sheet_name="Trades", index=False)
        w.to_excel(xw, sheet_name="Weekly P&L", index=False)
        pd.DataFrame({"rule": list(R.FINAL), "value": [str(v) for v in R.FINAL.values()]}).to_excel(xw, sheet_name="Rules", index=False)
        if lab.missing:
            pd.DataFrame(lab.missing).to_excel(xw, sheet_name="Skipped - no data", index=False)
    print(summ.to_string(index=False))
    print(yr.to_string(index=False))
    print(f"\nExcel saved: {xl}")


if __name__ == "__main__":
    main()
