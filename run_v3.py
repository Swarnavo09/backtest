"""Strategy v3 search: same rules as v2, but priced with REAL implied vols (NSE bhavcopy,
previous day's close per contract), trading-time decay and the real expiry calendar.
Adds OTM (theta) spreads and an expiry-day option.

    python fetch_bhav.py && python run_v3.py      # -> results/v3_grid.csv
"""
import itertools
from datetime import time
from multiprocessing import Pool

import pandas as pd

import realiv
import run_v2 as R
from strategy import Params, add_signals_v2, backtest

GRID = dict(
    sigset=["st", "st_ema", "ema_macd", "all3"],
    bias=["none", "live", "prev", "wlive_dlive_prevday"],
    sl=[30, 45, 60, 80, 120],
    exit_mode=["fixed", "trail", "hold"],
    short_offset=[-200, -100, 0, 100, 200],
    hedge=[200, 300],
    start=[time(9, 30), time(10, 15)],
    dte0=[False, True],
)
import sys
CONV = sys.argv[1] if len(sys.argv) > 1 else "mix70v"   # best fit to real prices (calibrate.py)
_bars = _vix = None


def _init():
    global _bars, _vix
    _bars, _vix = R.load()


def run_key(key):
    sigset, bias = key
    df = add_signals_v2(_bars, sigset, bias, st=(10, 3.0))
    rows = []
    for sl, em, off, hedge, start, z in itertools.product(GRID["sl"], GRID["exit_mode"], GRID["short_offset"],
                                                         GRID["hedge"], GRID["start"], GRID["dte0"]):
        p = R.mk(sl=sl, exit_mode=em, short_offset=off, hedge=hedge, start=start, dte0=z)
        tr = backtest(df, _vix, p)
        if tr.empty:
            continue
        d = tr.entry_ts.dt.strftime("%Y-%m-%d")
        r = dict(sigset=sigset, bias=bias, st="10,3", sl=sl, exit_mode=em, short_offset=off, hedge=hedge,
                 start=start.strftime("%H:%M"), dte0=z)
        r.update({f"tr_{k}": v for k, v in R.stats(tr[d <= R.TRAIN_END]).items()})
        r.update({f"te_{k}": v for k, v in R.stats(tr[d > R.TRAIN_END]).items()})
        r.update({f"y{k}": v for k, v in tr.groupby(tr.entry_ts.dt.year).net.sum().round().to_dict().items()})
        rows.append(r)
    return rows


def main():
    rv = realiv.install(CONV)          # installed before forking, so workers inherit it
    print("real IV points:", rv.n_iv)
    keys = list(itertools.product(GRID["sigset"], GRID["bias"]))
    with Pool(4, initializer=_init) as pool:
        rows = [r for chunk in pool.map(run_key, keys) for r in chunk]
    g = pd.DataFrame(rows)
    g.to_csv(R.OUT / f"v3_grid_{CONV}.csv", index=False)
    print(len(g), "combinations")
    print("profitable in train:", f"{(g.tr_net > 0).mean():.1%}", " test:", f"{(g.te_net > 0).mean():.1%}",
          " both:", f"{((g.tr_net > 0) & (g.te_net > 0)).mean():.1%}")


if __name__ == "__main__":
    main()
