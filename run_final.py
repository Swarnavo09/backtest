"""
Final strategy (STRATEGY.md) - last 2 years, 4 lots, next-week expiry.
Writes results/final/: trades.csv, weekly.csv, final_results.xlsx, FINAL_RESULTS.md, equity.png
"""
import os

import matplotlib
import numpy as np
import pandas as pd

from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

END = pd.Timestamp("2026-11-18")
START = END - pd.DateOffset(years=2)                      # last 2 years
DEV = ("2019-03-01", (START - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "final")

FINAL = dict(
    lots=4, expiry="next", max_trades=2, daily_cap=10_000, skip_after_losing_days=3,
    adx_min=25, htf_minutes=60, window=("09:25", "11:00"),          # entry filters (15-min closes 09:30..11:00)
    stop="rupee", sl_total=5_000, partial_total=None, final_total=15_000,   # SL 5k, target 15k (1:3)
    lock_trigger=5_000, lock_level=500, trail_frac=0.5, trail_mode="incremental",
    partial_at=None, st_exit=False, square_off="15:15",
)
TF = 15


def weekly_table(t):
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"])
    t["week"] = t["date"].dt.to_period("W-SUN")                 # Monday..Sunday weeks
    w = t.groupby("week").agg(trades=("net_pnl", "size"), net=("net_pnl", "sum")).reset_index()
    w["week_start"] = w.week.dt.start_time.dt.date
    w["week_end"] = w.week.dt.end_time.dt.date
    return w[["week_start", "week_end", "trades", "net"]]


def main():
    os.makedirs(OUT, exist_ok=True)
    df = C.load_1m()
    df = df[df.index >= "2018-09-01"]
    lab = Lab(df)
    t = lab.run(TF, START, END, **FINAL)
    dev = lab.run(TF, *DEV, **FINAL)
    t["date"] = pd.to_datetime(t["date"])
    w = weekly_table(t)
    w["ws"] = pd.to_datetime(w.week_start)

    s, sd = stat(t), stat(dev)
    eq = t.groupby("date").net_pnl.sum().cumsum()
    lines = [f"# Final strategy result: {START:%d-%b-%Y} → {END:%d-%b-%Y} (last 2 years, 4 lots, 15‑min)", "",
             "Rules: see `STRATEGY.md`. Option prices are modelled (Black‑Scholes, IV proxy), with 0.5‑pt slippage per leg and full charges.", "",
             "| Metric | Last 2 years | 2019 → Nov 2024 (selection data) |", "|---|---:|---:|",
             f"| Trades | {s['n']} | {sd['n']} |", f"| Win rate | {s['win']:.1f}% | {sd['win']:.1f}% |",
             f"| Net P&L | ₹{s['net']:,.0f} | ₹{sd['net']:,.0f} |", f"| Net per year | ₹{s['per_yr']:,.0f} | ₹{sd['per_yr']:,.0f} |",
             f"| Profit factor | {s['pf']:.2f} | {sd['pf']:.2f} |",
             f"| Max drawdown | ₹{(eq - eq.cummax()).min():,.0f} | |",
             f"| Avg win / avg loss | ₹{t.net_pnl[t.net_pnl > 0].mean():,.0f} / ₹{t.net_pnl[t.net_pnl <= 0].mean():,.0f} | |", ""]

    def year_block(label, mask_t, mask_w):
        tt, ww = t[mask_t], w[mask_w]
        if not len(tt):
            return None
        best, worst = ww.loc[ww.net.idxmax()], ww.loc[ww.net.idxmin()]
        return dict(period=label, trades=len(tt), win_pct=round((tt.net_pnl > 0).mean() * 100, 1), net=round(tt.net_pnl.sum()),
                    weeks_traded=len(ww), green_weeks=int((ww.net > 0).sum()),
                    max_week_profit=round(best.net), max_profit_week=f"{best.week_start:%d-%b-%y}",
                    max_week_loss=round(worst.net), max_loss_week=f"{worst.week_start:%d-%b-%y}",
                    bullish_net=round(tt.net_pnl[tt.direction == "Bullish"].sum()),
                    bearish_net=round(tt.net_pnl[tt.direction == "Bearish"].sum()))
    y1_end = START + pd.DateOffset(years=1)
    rows = [year_block(f"Year 1 ({START:%d-%b-%y} → {y1_end - pd.Timedelta(days=1):%d-%b-%y})", t.date < y1_end, w.ws < y1_end),
            year_block(f"Year 2 ({y1_end:%d-%b-%y} → {END:%d-%b-%y})", t.date >= y1_end, w.ws >= y1_end)]
    for y in sorted(t.date.dt.year.unique()):
        rows.append(year_block(f"Calendar {y}" + (" (part)" if y in (START.year, END.year) else ""), t.date.dt.year == y, w.ws.dt.year == y))
    yr = pd.DataFrame([r for r in rows if r])
    lines += ["## By year, with best and worst week", "",
              "| Period | Trades | Win % | Net | Weeks traded (green) | Max profit in a week | Max loss in a week | Bullish net | Bearish net |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in yr.iterrows():
        lines.append(f"| {r.period} | {r.trades} | {r.win_pct} | ₹{r.net:,} | {r.weeks_traded} ({r.green_weeks}) | "
                     f"₹{r.max_week_profit:,} (wk of {r.max_profit_week}) | ₹{r.max_week_loss:,} (wk of {r.max_loss_week}) | "
                     f"₹{r.bullish_net:,} | ₹{r.bearish_net:,} |")
    lines += ["", "## Exit reasons (last 2 years)", "", "| Exit | Trades | Avg net | Total |", "|---|---:|---:|---:|"]
    t["exit_group"] = np.where(t.exit_reason.str.startswith("trailing"), "trailing stop / profit lock", t.exit_reason)
    for k, g in t.groupby("exit_group").net_pnl:
        lines.append(f"| {k} | {len(g)} | ₹{g.mean():,.0f} | ₹{g.sum():,.0f} |")
    md = "\n".join(lines)
    open(os.path.join(OUT, "FINAL_RESULTS.md"), "w").write(md + "\n")
    print(md)

    t.drop(columns=["exit_group"]).to_csv(os.path.join(OUT, "trades.csv"), index=False)
    w.drop(columns=["ws"]).to_csv(os.path.join(OUT, "weekly.csv"), index=False)
    m = t.groupby(t.date.dt.to_period("M")).net_pnl.agg(trades="size", net="sum").reset_index()
    m["date"] = m["date"].astype(str)
    with pd.ExcelWriter(os.path.join(OUT, "final_results.xlsx")) as xw:
        pd.DataFrame({"Rule": list(FINAL.keys()), "Value": [str(v) for v in FINAL.values()]}).to_excel(xw, sheet_name="Rules", index=False)
        yr.to_excel(xw, sheet_name="Yearly + best-worst week", index=False)
        t.drop(columns=["exit_group"]).assign(date=t.date.dt.date).to_excel(xw, sheet_name="Trades (2 years)", index=False)
        w.drop(columns=["ws"]).to_excel(xw, sheet_name="Weekly P&L", index=False)
        m.to_excel(xw, sheet_name="Monthly P&L", index=False)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(eq.index, eq.values / 1000, lw=1.8)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_ylabel("cumulative net P&L, ₹ thousand")
    ax.set_title("Final strategy, last 2 years (4 lots, 15‑min, SL 5k / target 15k)")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "equity.png"), dpi=130)


if __name__ == "__main__":
    main()
