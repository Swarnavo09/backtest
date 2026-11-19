"""Collect backtest results into report/data.json and build report/index.html.

    python run_backtest.py && python build_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_backtest import load_all, pick, to_params
from strategy import add_indicators, backtest, summarize

ROOT = Path(__file__).parent
RES, REP = ROOT / "results", ROOT / "report"

KEEP = ["tf", "ma_fast", "ma_slow", "st_period", "st_mult", "macd_zero", "sl", "rr",
        "exit_mode", "st_exit", "hedge", "short_offset", "htf", "max_trades"]


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 2)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def daily_equity(tr: pd.DataFrame, days) -> list:
    pnl = tr.groupby(tr.entry_ts.dt.date).net.sum() if len(tr) else pd.Series(dtype=float)
    eq, out = 0.0, []
    for d in days:
        eq += float(pnl.get(d, 0.0))
        out.append({"label": d.strftime("%d %b"), "y": round(eq, 0)})
    return out


def excursions(df: pd.DataFrame, tr: pd.DataFrame, sl: float) -> dict:
    """For every entry: how far did price go in our favour before a 1R (=SL) stop?"""
    hits = {k: 0 for k in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)}
    mfe_list = []
    for _, t in tr.iterrows():
        side = 1 if t.side == "BULL PUT" else -1
        seg = df[(df.index >= t.entry_ts) & (df.index.date == t.entry_ts.date())]
        seg = seg[[x.time() < pd.Timestamp("15:15").time() for x in seg.index]]
        best = 0.0
        for _, b in seg.iterrows():
            adverse = (t.spot_in - b.Low) if side == 1 else (b.High - t.spot_in)
            if adverse >= sl:
                break
            fav = (b.High - t.spot_in) if side == 1 else (t.spot_in - b.Low)
            best = max(best, fav)
        mfe_list.append(best)
        for k in hits:
            if best >= k * sl:
                hits[k] += 1
    n = max(len(tr), 1)
    return {"n": len(tr), "sl": sl,
            "reach": {f"{k:g}R": round(100 * v / n, 1) for k, v in hits.items()},
            "median_mfe": round(float(np.median(mfe_list)), 1) if mfe_list else 0}


def example_session(df: pd.DataFrame, tr: pd.DataFrame, p) -> dict:
    """Pick the trade with the largest net gain and return that session's bars."""
    t = tr.sort_values("net", ascending=False).iloc[0]
    day = t.entry_ts.date()
    s = df[df.index.date == day]
    idx = list(s.index)
    side = 1 if t.side == "BULL PUT" else -1
    i_in = idx.index(t.entry_ts)
    i_out = idx.index(t.exit_ts) if t.exit_ts in idx else len(idx) - 1
    return {
        "date": day.strftime("%d %b %Y"), "fast": p.ma_fast, "slow": p.ma_slow,
        "bars": [{"t": x.strftime("%H:%M"), "o": r.Open, "h": r.High, "l": r.Low, "c": r.Close}
                 for x, r in s.iterrows()],
        "ef": s.ema_f.round(2).tolist(), "es": s.ema_s.round(2).tolist(),
        "st": s.st_line.round(2).tolist(), "sd": s.st_dir.astype(int).tolist(),
        "macd": s.macd.round(2).tolist(), "sig": s.sig.round(2).tolist(),
        "hist": (s.macd - s.sig).round(2).tolist(),
        "trades": [{"side": side, "i_in": i_in, "i_out": i_out, "entry": t.spot_in,
                    "exit": t.spot_out, "sl": t.spot_in - side * p.sl,
                    "tgt": t.spot_in + side * p.rr * p.sl}],
        "trade": t.drop(["iv"]).astype(str).to_dict(),
    }


def main() -> None:
    vix, bars, htf, days, split = load_all()
    summary = json.loads((RES / "summary.json").read_text())
    out = {"meta": {k: summary[k] for k in ("sessions", "first", "last", "oos_from", "n_is")}}
    out["meta"]["last_close"] = round(float(bars[5].Close.iloc[-1]), 2)
    out["meta"]["vix_last"] = round(float(vix.iloc[-1]), 2)

    for stage in ("stage1", "stage2"):
        grid = pd.read_csv(RES / f"grid_{stage}.csv")
        st = {"combos": len(grid),
              "pct_profitable_all": round(100 * (grid.all_net > 0).mean(), 1),
              "pct_profitable_oos": round(100 * (grid.oos_net > 0).mean(), 1),
              "tf": {}}
        for tf in (5, 10, 15):
            best = pick(grid, tf)
            p = to_params(best)
            df = add_indicators(bars[tf], p, htf)
            tr = backtest(df, vix, p)
            g = grid[grid.tf == tf]
            st["tf"][tf] = {
                "params": {k: best[k] for k in KEEP},
                "all": summarize(tr, len(days)),
                "is": {k.replace("is_", ""): best[k] for k in best.index if k.startswith("is_")},
                "oos": {k.replace("oos_", ""): best[k] for k in best.index if k.startswith("oos_")},
                "gross": round(tr.gross.sum(), 0), "costs": round(tr.costs.sum(), 0),
                "spot_pts": round(tr.spot_pts.sum(), 0),
                "avg_credit": round(tr.credit.mean(), 1),
                "pct_profitable_all": round(100 * (g.all_net > 0).mean(), 1),
                "pct_profitable_oos": round(100 * (g.oos_net > 0).mean(), 1),
                "equity": daily_equity(tr, days),
                "reasons": tr.reason.value_counts().to_dict(),
                "excursions": excursions(df, tr, p.sl),
                "summary": summary[stage][str(tf)],
            }
            if stage == "stage2":
                # SL x exit-mode heatmap, other parameters fixed at the chosen setup
                mask = np.ones(len(g), dtype=bool)
                for k in ("ma_fast", "ma_slow", "st_period", "st_mult", "macd_zero",
                          "short_offset", "htf", "max_trades"):
                    mask &= (g[k] == best[k]).values
                h = g[mask]
                st["tf"][tf]["heat"] = {
                    f"{int(r.sl)}|{r.exit_mode}": {"all": r.all_net, "oos": r.oos_net}
                    for r in h.itertuples()}
                st["tf"][tf]["example"] = example_session(df, tr, p)
                # how much each stage-2 switch helps on average
                st["tf"][tf]["switches"] = {
                    "short_offset": g.groupby("short_offset").all_net.median().to_dict(),
                    "htf": g.groupby("htf").all_net.median().to_dict(),
                    "max_trades": g.groupby("max_trades").all_net.median().to_dict(),
                    "ma": g.groupby(["ma_fast"]).all_net.median().to_dict(),
                    "st": g.groupby(["st_period", "st_mult"]).all_net.median()
                           .rename(lambda x: f"{x[0]},{x[1]:g}" if isinstance(x, tuple) else x).to_dict(),
                    "exit_mode": g.groupby("exit_mode").all_net.median().to_dict(),
                    "sl": g.groupby("sl").all_net.median().to_dict(),
                }
        out[stage] = st

    ys = RES / "year_summary.json"
    if ys.exists():
        out["year"] = json.loads(ys.read_text())
        ls = RES / "year_lots_slippage.json"
        if ls.exists():
            out["year"]["lots_slip"] = json.loads(ls.read_text())

    REP.mkdir(exist_ok=True)
    data = json.dumps(clean(out), separators=(",", ":"), default=str)
    (REP / "data.json").write_text(data)
    tpl = (REP / "template.html").read_text()
    js = (REP / "charts.js").read_text()
    html = tpl.replace("/*__CHARTS__*/", js).replace("/*__DATA__*/", f"const DATA = {data};")
    (REP / "index.html").write_text(html)
    print("wrote report/data.json and report/index.html", len(html) // 1024, "KB")


if __name__ == "__main__":
    main()
