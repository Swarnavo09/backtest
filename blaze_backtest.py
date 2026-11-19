#!/usr/bin/env python3
"""
Blaze Butterfly backtester (NIFTY 1:2:1 Broken Wing Put Butterfly), 2-lot version.

Structure (x LOTS_MULT, default 2):
    BUY  2 lots PE  K1 = ATM - offset            (upper wing)
    SELL 4 lots PE  K2 = K1 - 200                 (body)
    BUY  2 lots PE  K3 = K2 - 400                 (lower hedge)

Rules implemented
  * Entry: first trading day of the week (Monday) at the close.
  * Expiry: first NIFTY weekly expiry AFTER that week's Friday
    (Tue-expiry era: skip tomorrow's Tuesday, use next week's Tuesday;
     Thu-expiry era, Jan-Aug 2025: skip this Thursday, use next Thursday).
  * Strike search (--mode):
      strict (default): start 200 pts below ATM and roll the whole structure
        lower in 50-pt steps; take the closest offset whose net CREDIT is
        > 0 and <= 0.6 % of margin. Weeks with no such setup are skipped.
      video: same roll, but take the first offset whose net premium lies
        between a 0.7 % debit and a 0.6 % credit (the video's filter).
  * Target +1.5 % of margin, stop -1 % of margin, otherwise exit Friday
    (last trading day of the week if Friday is a holiday).
  * No adjustments.

Data: free NSE F&O UDiFF bhavcopies (end-of-day). Because the data is EOD:
  * entry price  = Monday closing price (close ~ CAS 3:35 PM price),
  * target/stop  = checked on each day's closing prices,
  * Friday exit  = Friday closing price (not 2:30 PM).
Use --fill-at-levels to book a breached target/stop at exactly its level
(assumes the intraday touch was filled at the level) instead of at the close.

Usage
    pip install pandas openpyxl
    python blaze_backtest.py                       # 2025-01-01 .. today
    python blaze_backtest.py --margin-per-set 100000 --lots 2
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

UDIFF_URL = ("https://nsearchives.nseindia.com/content/fo/"
             "BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

STRIKE_STEP = 50
WING = 200          # K1 -> K2
HEDGE = 400         # K2 -> K3
BASE_OFFSET = 200   # ATM -> K1
MAX_OFFSET = 2000


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
def fetch_day(day: dt.date, cache: Path, offline: bool) -> pd.DataFrame | None:
    """Return the NIFTY index-option rows for `day`, or None on a holiday."""
    cache.mkdir(parents=True, exist_ok=True)
    zpath = cache / f"{day:%Y%m%d}.csv.zip"
    hol = cache / f"{day:%Y%m%d}.holiday"
    if hol.exists():
        return None
    if not zpath.exists():
        if offline:
            return None
        req = urllib.request.Request(UDIFF_URL.format(d=day), headers=HEADERS)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    zpath.write_bytes(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    hol.touch()
                    return None
                time.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** attempt)
        else:
            print(f"  ! could not download {day}", file=sys.stderr)
            return None
        time.sleep(0.35)  # be polite to NSE
    with zipfile.ZipFile(zpath) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(io.TextIOWrapper(f, "utf-8"))
    df.columns = [c.strip() for c in df.columns]
    df = df[(df["TckrSymb"].str.strip() == "NIFTY") & (df["OptnTp"].str.strip() == "PE")]
    if df.empty:
        return None
    px = df["ClsPric"].where(df["ClsPric"] > 0, df["SttlmPric"])
    out = pd.DataFrame({
        "expiry": pd.to_datetime(df["XpryDt"]).dt.date,
        "strike": df["StrkPric"].astype(float),
        "price": px.astype(float),
        "volume": df["TtlTradgVol"].fillna(0).astype(float),
        "spot": df["UndrlygPric"].astype(float),
        "lot": df["NewBrdLotQty"].astype(int),
    })
    return out


def load_all(start: dt.date, end: dt.date, cache: Path, offline: bool) -> dict[dt.date, pd.DataFrame]:
    days, d = {}, start
    total = (end - start).days + 1
    i = 0
    while d <= end:
        i += 1
        if d.weekday() < 5:
            df = fetch_day(d, cache, offline)
            if df is not None:
                days[d] = df
            if i % 20 == 0:
                print(f"  loaded up to {d} ({len(days)} trading days)", file=sys.stderr)
        d += dt.timedelta(days=1)
    return days


# --------------------------------------------------------------------------
# Charges (Indian F&O options, approx. discount broker)
# --------------------------------------------------------------------------
def leg_charges(premium: float, qty: int, side: str, brokerage: float) -> float:
    turnover = premium * qty
    stt = 0.001 * turnover if side == "S" else 0.0
    exch = 0.0003503 * turnover
    sebi = turnover * 10 / 1e7
    stamp = 0.00003 * turnover if side == "B" else 0.0
    gst = 0.18 * (brokerage + exch + sebi)
    return brokerage + stt + exch + sebi + stamp + gst


# --------------------------------------------------------------------------
# Strategy
# --------------------------------------------------------------------------
def price_of(chain: pd.DataFrame, strike: float) -> float | None:
    r = chain.loc[chain["strike"] == strike, "price"]
    if r.empty or not (r.iloc[0] > 0):
        return None
    return float(r.iloc[0])


def select_strikes(chain: pd.DataFrame, spot: float, lot: int, margin_set: float,
                   mode: str):
    """Return (offset, K1, K2, K3, p1, p2, p3, credit_pts) or None.

    strict : closest offset >= 200 whose net CREDIT is > 0 and <= 0.6 % of margin
    video  : first offset (from 200, rolling lower) whose net premium lies
             between a 0.7 % debit and a 0.6 % credit
    """
    atm = round(spot / STRIKE_STEP) * STRIKE_STEP
    cap = 0.006 * margin_set
    debit_cap = 0.007 * margin_set
    for off in range(BASE_OFFSET, MAX_OFFSET + 1, STRIKE_STEP):
        k1 = atm - off
        k2 = k1 - WING
        k3 = k2 - HEDGE
        p = [price_of(chain, k) for k in (k1, k2, k3)]
        if None in p:
            continue
        credit = 2 * p[1] - p[0] - p[2]           # points per 1:2:1 set
        rs = credit * lot
        ok = (0 < rs <= cap) if mode == "strict" else (-debit_cap <= rs <= cap)
        if ok:
            return (off, k1, k2, k3, *p, credit)
    return None


def run(days: dict[dt.date, pd.DataFrame], margin_set: float, lots: int,
        mode: str, fill_at_levels: bool, brokerage: float, costs: bool):
    tdays = sorted(days)
    weeks: dict[tuple, list[dt.date]] = {}
    for d in tdays:
        weeks.setdefault(d.isocalendar()[:2], []).append(d)

    rows = []
    for (yr, wk), wdays in sorted(weeks.items()):
        entry = wdays[0]
        friday = entry + dt.timedelta(days=4 - entry.weekday())
        chain_all = days[entry]
        expiries = sorted(e for e in chain_all["expiry"].unique() if e > friday)
        base = {"week": f"{yr}-W{wk:02d}", "entry_date": entry}
        if not expiries or len(wdays) < 2:
            rows.append({**base, "status": "SKIP", "reason": "no expiry / no exit day"})
            continue
        expiry = expiries[0]
        chain = chain_all[chain_all["expiry"] == expiry]
        spot = float(chain["spot"].iloc[0])
        lot = int(chain["lot"].iloc[0])
        margin = margin_set * lots
        sel = select_strikes(chain, spot, lot, margin_set, mode)
        if sel is None:
            rows.append({**base, "expiry": expiry, "spot": spot, "lot_size": lot,
                         "status": "SKIP", "reason": "no setup meets the credit/debit filter"})
            continue
        off, k1, k2, k3, p1, p2, p3, credit = sel
        q1, q2, q3 = 1 * lots * lot, 2 * lots * lot, 1 * lots * lot
        target, stop = 0.015 * margin, -0.01 * margin

        last = {k1: p1, k2: p2, k3: p3}
        exit_day, exit_reason, pnl = None, None, None
        for d in wdays[1:]:
            c = days[d]
            c = c[c["expiry"] == expiry]
            for k in (k1, k2, k3):
                v = price_of(c, k)
                if v is not None:
                    last[k] = v
            mtm = ((last[k1] - p1) * q1 - (last[k2] - p2) * q2 + (last[k3] - p3) * q3)
            if mtm >= target:
                exit_day, exit_reason, pnl = d, "TARGET", (target if fill_at_levels else mtm)
                break
            if mtm <= stop:
                exit_day, exit_reason, pnl = d, "STOPLOSS", (stop if fill_at_levels else mtm)
                break
            exit_day, exit_reason, pnl = d, "FRIDAY EXIT", mtm
        if exit_reason == "FRIDAY EXIT" and exit_day.weekday() != 4:
            exit_reason = "WEEK-END EXIT"

        ch = 0.0
        if costs:
            x1, x2, x3 = last[k1], last[k2], last[k3]
            ch = (leg_charges(p1, q1, "B", brokerage) + leg_charges(p2, q2, "S", brokerage)
                  + leg_charges(p3, q3, "B", brokerage) + leg_charges(x1, q1, "S", brokerage)
                  + leg_charges(x2, q2, "B", brokerage) + leg_charges(x3, q3, "S", brokerage))
        rows.append({
            **base, "exit_date": exit_day, "expiry": expiry, "spot": round(spot, 2),
            "lot_size": lot, "offset": off,
            "buy_K1": int(k1), "sell_K2": int(k2), "buy_K3": int(k3),
            "p1": p1, "p2": p2, "p3": p3,
            "qty": f"{q1}/{q2}/{q3}",
            "net_credit_pts": round(credit, 2),
            "net_credit_rs": round(credit * lot * lots, 2),
            "margin_rs": margin, "target_rs": target, "stop_rs": stop,
            "status": exit_reason,
            "gross_pnl": round(pnl, 2), "charges": round(ch, 2),
            "net_pnl": round(pnl - ch, 2),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def summarise(trades: pd.DataFrame, key: str) -> pd.DataFrame:
    t = trades[trades["status"] != "SKIP"].copy()
    if t.empty:
        return pd.DataFrame()
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t[key] = t["entry_date"].dt.strftime("%Y-%m" if key == "month" else "%Y")
    g = t.groupby(key)
    out = pd.DataFrame({
        "trades": g.size(),
        "wins": g["net_pnl"].apply(lambda s: (s > 0).sum()),
        "losses": g["net_pnl"].apply(lambda s: (s <= 0).sum()),
        "targets": g["status"].apply(lambda s: (s == "TARGET").sum()),
        "stops": g["status"].apply(lambda s: (s == "STOPLOSS").sum()),
        "time_exits": g["status"].apply(lambda s: s.str.contains("EXIT").sum()),
        "gross_profit": g["net_pnl"].apply(lambda s: s[s > 0].sum()),
        "gross_loss": g["net_pnl"].apply(lambda s: s[s <= 0].sum()),
        "charges": g["charges"].sum(),
        "net_pnl": g["net_pnl"].sum(),
    })
    out["win_rate_%"] = (100 * out["wins"] / out["trades"]).round(1)
    margin = t["margin_rs"].iloc[0]
    out["return_on_margin_%"] = (100 * out["net_pnl"] / margin).round(2)
    if key == "month":
        skipped = trades[trades["status"] == "SKIP"].copy()
        skipped["m"] = pd.to_datetime(skipped["entry_date"]).dt.strftime("%Y-%m")
        out["skipped_weeks"] = skipped.groupby("m").size().reindex(out.index).fillna(0).astype(int)
    else:
        eq = t.sort_values("entry_date").set_index(key)["net_pnl"]
        dd = {}
        for y, s in eq.groupby(level=0):
            c = s.cumsum()
            dd[y] = (c - c.cummax().clip(lower=0)).min()
        out["max_drawdown"] = pd.Series(dd)
    return out.round(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--lots", type=int, default=2, help="lot multiplier (2 => 2/4/2 lots)")
    ap.add_argument("--margin-per-set", type=float, default=100000,
                    help="margin for ONE 1:2:1 set in Rs (default 100000)")
    ap.add_argument("--mode", choices=["strict", "video"], default="strict",
                    help="strict: always net credit <= 0.6%%; video: credit <= 0.6%% or debit <= 0.7%%")
    ap.add_argument("--fill-at-levels", action="store_true",
                    help="book target/stop at exactly +1.5%%/-1%% instead of at the close")
    ap.add_argument("--brokerage", type=float, default=20.0, help="Rs per order (leg)")
    ap.add_argument("--no-costs", action="store_true")
    ap.add_argument("--cache", default="data/fo")
    ap.add_argument("--out", default="results")
    ap.add_argument("--offline", action="store_true", help="use cached files only")
    a = ap.parse_args()

    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    print(f"Loading NSE F&O bhavcopies {start} .. {end}", file=sys.stderr)
    days = load_all(start, end, Path(a.cache), a.offline)
    if not days:
        sys.exit("No data loaded. Check internet access to nsearchives.nseindia.com.")

    trades = run(days, a.margin_per_set, a.lots, a.mode, a.fill_at_levels,
                 a.brokerage, not a.no_costs)
    monthly, yearly = summarise(trades, "month"), summarise(trades, "year")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / "weekly_trades.csv", index=False)
    monthly.to_csv(out / "monthly_summary.csv")
    yearly.to_csv(out / "yearly_summary.csv")
    with pd.ExcelWriter(out / "blaze_butterfly_backtest.xlsx") as xw:
        trades.to_excel(xw, sheet_name="Weekly trades", index=False)
        monthly.to_excel(xw, sheet_name="Monthly")
        yearly.to_excel(xw, sheet_name="Yearly")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 200)
    cols = ["week", "entry_date", "exit_date", "spot", "buy_K1", "sell_K2", "buy_K3",
            "net_credit_rs", "status", "gross_pnl", "charges", "net_pnl"]
    print("\n=== WEEKLY TRADES ===")
    print(trades.reindex(columns=cols).to_string(index=False))
    print("\n=== MONTHLY ===")
    print(monthly.to_string())
    print("\n=== YEARLY ===")
    print(yearly.to_string())
    print(f"\nFiles written to {out.resolve()}/")


if __name__ == "__main__":
    main()
