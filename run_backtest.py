"""
Run every backtest for the last 3 years with 4 lots and write the results.

  python data/build_data.py      # once, downloads + builds data/nifty_1m.parquet
  python run_backtest.py         # writes results/*.csv, results/backtest_results.xlsx,
                                 #        results/SUMMARY.md, results/equity_curves.png

Strategies compared:
  CS-5m / CS-10m / CS-15m : Supertrend(10,3)+ADX(14) credit spreads on 5/10/15-min candles
  Prev A+B (debit)        : previous playbook (narrow ORB + PDH/PDL breakout) as debit spreads
"""
import os

import matplotlib
import numpy as np
import pandas as pd

from bt import common as C, credit_spread as CS, playbook_ab as AB

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

END = pd.Timestamp("2026-11-18")
START = END - pd.DateOffset(years=3)  # last 3 years
LOTS = 4
CAPITAL = LOTS * CS.MARGIN_PER_LOT   # Rs 1.6 lakh: margin basis used for return %
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def summarise(name, t):
    if t.empty:
        return dict(strategy=name, trades=0)
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"])
    daily = t.groupby("date").net_pnl.sum()
    eq = daily.cumsum()
    monthly = daily.resample("ME").sum()
    monthly = monthly[monthly.index.isin(daily.resample("ME").sum().index[daily.resample("ME").count() > 0])]
    wins, losses = t.net_pnl[t.net_pnl > 0], t.net_pnl[t.net_pnl <= 0]
    row = dict(
        strategy=name, trades=len(t), win_rate_pct=round(len(wins) / len(t) * 100, 1),
        net_pnl=round(t.net_pnl.sum()), return_on_1_6L_pct=round(t.net_pnl.sum() / CAPITAL * 100, 1),
        avg_per_trade=round(t.net_pnl.mean()), avg_win=round(wins.mean()) if len(wins) else 0,
        avg_loss=round(losses.mean()) if len(losses) else 0,
        profit_factor=round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else np.inf,
        max_drawdown=round((eq - eq.cummax()).min()), profitable_months_pct=round((monthly > 0).mean() * 100),
        best_month=round(monthly.max()), worst_month=round(monthly.min()), total_charges=round(t.charges.sum()),
        bullish_trades=int((t.direction == "Bullish").sum()), bullish_net=round(t.net_pnl[t.direction == "Bullish"].sum()),
        bullish_win_pct=round((t.net_pnl[t.direction == "Bullish"] > 0).mean() * 100, 1),
        bearish_trades=int((t.direction == "Bearish").sum()), bearish_net=round(t.net_pnl[t.direction == "Bearish"].sum()),
        bearish_win_pct=round((t.net_pnl[t.direction == "Bearish"] > 0).mean() * 100, 1),
    )
    for y, v in daily.groupby(daily.index.year).sum().items():
        row[f"net_{y}"] = round(v)
    return row


def main():
    os.makedirs(OUT, exist_ok=True)
    df = C.load_1m()
    df = df[df.index >= START - pd.DateOffset(months=6)]  # warm-up for Supertrend/ADX/vol
    results, day_logs = {}, {}
    for m in (5, 10, 15):
        print(f"running credit spread on {m}-min candles ...")
        results[f"CS-{m}m"], day_logs[f"CS-{m}m"] = CS.run(df, m, START, END, lots=LOTS)
    print("running previous playbook A+B as debit spreads ...")
    results["Prev A+B (debit)"] = AB.run(df, START, END, lots=LOTS)
    print("sensitivity: 10-min, entry only on the flip candle itself ...")
    sens, _ = CS.run(df, 10, START, END, lots=LOTS, flip_candle_only=True)

    summary = pd.DataFrame([summarise(k, v) for k, v in results.items()] + [summarise("CS-10m flip-candle-only", sens)])
    summary = summary.set_index("strategy")
    print(summary.T.to_string())

    # ---------- files
    for k, v in results.items():
        v.to_csv(os.path.join(OUT, f"trades_{k.replace(' ', '_').replace('+', '').replace('(', '').replace(')', '')}.csv"), index=False)
    with pd.ExcelWriter(os.path.join(OUT, "backtest_results.xlsx")) as xw:
        summary.T.to_excel(xw, sheet_name="Summary")
        for k, v in results.items():
            v.to_excel(xw, sheet_name=k.replace("+", "").replace("(", "").replace(")", "")[:31], index=False)
        for k, v in day_logs.items():
            v.to_excel(xw, sheet_name=f"{k} days"[:31], index=False)
    summary.T.to_csv(os.path.join(OUT, "summary.csv"))

    # ---------- equity curves
    fig, ax = plt.subplots(figsize=(11, 5))
    for k, v in results.items():
        if v.empty:
            continue
        s = v.assign(date=pd.to_datetime(v.date)).groupby("date").net_pnl.sum().cumsum()
        ax.plot(s.index, s.values / 1e5, lw=2 if k.startswith("Prev") else 1.4, label=f"{k}  (₹{s.iat[-1] / 1e5:+.2f} L)")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_ylabel("cumulative net P&L, ₹ lakh (4 lots, after charges)")
    ax.set_title(f"NIFTY options backtest {START:%d-%b-%Y} to {END:%d-%b-%Y}")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "equity_curves.png"), dpi=130)
    return summary


if __name__ == "__main__":
    main()
