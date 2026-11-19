"""Strategy v2: weekly/daily candle bias + 15-minute indicator trigger, hedged spreads.

    python fetch_upstox.py 2022-01-01 2026-11-18   (saved as data/nifty_5m_5y.csv)
    python run_v2.py

Rules being searched
  * Bias: trade bullish only when the chosen weekly AND daily candles are green,
    bearish only when both are red; mixed colours = skip the day.
  * Trigger on 15-minute candles from a subset of Supertrend / EMA / MACD.
  * Bull put or bear call spread, max 1 trade a day, entries 09:30/10:15-13:30,
    everything squared off at 14:45 (MIS).
  * All costs at 6 lots: brokerage, STT, exchange fees, SEBI, stamp, GST, slippage.

Parameters are chosen on 2022-2024 ONLY. 2025-2026 is never looked at during the
search; it is the honest test.
"""
from __future__ import annotations

import itertools
import json
from datetime import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import Params, add_signals_v2, backtest, load_bars

ROOT = Path(__file__).parent
DATA, OUT = ROOT / "data", ROOT / "results"
LOTS = 6
TRAIN_END = "2024-12-31"
TF = 15

GRID = dict(
    sigset=["st", "st_ema", "st_macd", "ema_macd", "all3"],
    bias=["none", "live", "prev", "wprev_dlive", "wlive_dlive_prevday"],
    st=[(10, 3.0), (10, 2.0)],
    sl=[30, 45, 60, 80],
    exit_mode=["fixed", "be", "trail", "hold"],
    short_offset=[0, 100, 200],
    hedge=[200, 300],
    start=[time(9, 30), time(10, 15)],
)

_bars = _vix = None


def load():
    vix = pd.read_csv(DATA / "indiavix_1d_5y.csv", index_col=0, parse_dates=True)["Close"]
    vix.index = pd.to_datetime(vix.index).normalize()
    b = load_bars(DATA / "nifty_5m_5y.csv", TF)
    full = b.groupby(b.index.date).size()
    keep = set(full[full >= 0.9 * full.max()].index)
    return b[[d in keep for d in b.index.date]], vix


def _init():
    global _bars, _vix
    _bars, _vix = load()


def mk(**kw) -> Params:
    return Params(tf=TF, squareoff=time(14, 45), last_entry=time(13, 30), lots=LOTS, max_trades=1, **kw)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return dict(n=0, net=0.0, net1=0.0, pf=0.0, dd=0.0, win=0.0)
    eq = tr.net.cumsum()
    w, l = tr.net[tr.net > 0].sum(), -tr.net[tr.net <= 0].sum()
    return dict(n=len(tr), net=round(tr.net.sum()), net1=round(tr.net_1lot.sum()),
                pf=round(w / l, 2) if l > 0 else 9.99,
                dd=round(float((eq - eq.cummax().clip(lower=0)).min())),
                win=round(100 * (tr.net > 0).mean(), 1))


def run_key(key):
    sigset, bias, st = key
    df = add_signals_v2(_bars, sigset, bias, st=st)
    rows = []
    for sl, em, off, hedge, start in itertools.product(GRID["sl"], GRID["exit_mode"], GRID["short_offset"],
                                                      GRID["hedge"], GRID["start"]):
        p = mk(sl=sl, exit_mode=em, short_offset=off, hedge=hedge, start=start)
        tr = backtest(df, _vix, p)
        if tr.empty:
            continue
        d = tr.entry_ts.dt.strftime("%Y-%m-%d")
        tr_tr, tr_te = tr[d <= TRAIN_END], tr[d > TRAIN_END]
        yrs = tr.groupby(tr.entry_ts.dt.year).net.sum().round().to_dict()
        r = dict(sigset=sigset, bias=bias, st=f"{st[0]},{st[1]:g}", sl=sl, exit_mode=em,
                 short_offset=off, hedge=hedge, start=start.strftime("%H:%M"))
        r.update({f"tr_{k}": v for k, v in stats(tr_tr).items()})
        r.update({f"te_{k}": v for k, v in stats(tr_te).items()})
        r.update({f"y{k}": v for k, v in yrs.items()})
        rows.append(r)
    return rows


def main() -> None:
    OUT.mkdir(exist_ok=True)
    keys = list(itertools.product(GRID["sigset"], GRID["bias"], GRID["st"]))
    with Pool(4, initializer=_init) as pool:
        rows = [r for chunk in pool.map(run_key, keys) for r in chunk]
    g = pd.DataFrame(rows)
    g.to_csv(OUT / "v2_grid.csv", index=False)
    print(len(g), "combinations")
    print("profitable in train:", f"{(g.tr_net > 0).mean():.1%}", " in test:", f"{(g.te_net > 0).mean():.1%}",
          " both:", f"{((g.tr_net > 0) & (g.te_net > 0)).mean():.1%}")


if __name__ == "__main__":
    main()
