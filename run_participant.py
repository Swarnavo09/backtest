"""Does FII / Pro / Client positioning (NSE participant OI, published each evening)
give a useful bias for the NEXT day's trade?

Signals use only the file published on day d and are applied on the next trading day.
  fut_net  = index futures long - short (contracts)
  opt_net  = (index call long - call short) - (index put long - put short)

    python run_participant.py   -> results/participant.json
"""
import json
from dataclasses import replace
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import run_ar_filters as AF
import run_exits as E
import run_trailing as T
import run_v2 as R
import run_vwap as V
from strategy import add_signals_v2, backtest

ROOT = R.ROOT


def signals():
    p = pd.read_csv(ROOT / "data" / "participant_oi.csv", parse_dates=["date"])
    p["fut_net"] = p.fut_idx_long - p.fut_idx_short
    p["opt_net"] = (p.call_long - p.call_short) - (p.put_long - p.put_short)
    p["fut_ratio"] = p.fut_idx_long / (p.fut_idx_long + p.fut_idx_short)
    w = p.pivot(index="date", columns="who", values=["fut_net", "opt_net", "fut_ratio"])
    s = pd.DataFrame(index=w.index)
    fii_f, fii_o = w["fut_net"]["FII"], w["opt_net"]["FII"]
    pro_f, pro_o = w["fut_net"]["Pro"], w["opt_net"]["Pro"]
    cli_f, cli_o = w["fut_net"]["Client"], w["opt_net"]["Client"]
    s["FII futures net (level)"] = np.sign(fii_f)
    s["FII futures net (change)"] = np.sign(fii_f.diff())
    s["FII futures long% vs 20-day avg"] = np.sign(w["fut_ratio"]["FII"] - w["fut_ratio"]["FII"].rolling(20).mean())
    s["FII options net (change)"] = np.sign(fii_o.diff())
    s["FII futures + options agree (change)"] = np.where(np.sign(fii_f.diff()) == np.sign(fii_o.diff()), np.sign(fii_f.diff()), 0)
    s["Pro futures net (change)"] = np.sign(pro_f.diff())
    s["Pro options net (change)"] = np.sign(pro_o.diff())
    s["FII + Pro futures (change)"] = np.sign((fii_f + pro_f).diff())
    s["FII + Pro options (change)"] = np.sign((fii_o + pro_o).diff())
    s["Opposite to Clients, futures (change)"] = -np.sign(cli_f.diff())
    s["Opposite to Clients, options (change)"] = -np.sign(cli_o.diff())
    s["Opposite to Clients, futures (level vs 20d)"] = -np.sign(cli_f - cli_f.rolling(20).mean())
    s["FII + Pro vs Clients all agree (change)"] = np.where(
        (np.sign((fii_f + pro_f).diff()) == -np.sign(cli_f.diff())) & (np.sign((fii_o + pro_o).diff()) == -np.sign(cli_o.diff()))
        & (np.sign((fii_f + pro_f).diff()) == np.sign((fii_o + pro_o).diff())), np.sign((fii_f + pro_f).diff()), 0)
    s["Smart money futures, contrarian"] = -np.sign((fii_f + pro_f).diff())   # sanity check: the opposite
    return s.fillna(0)


def next_day_map(sig: pd.DataFrame, days):
    """Signal published on day d -> bias for the next trading day."""
    days = sorted(days)
    nxt = {days[i]: days[i + 1] for i in range(len(days) - 1)}
    out = {}
    for d, row in sig.iterrows():
        nd = nxt.get(d.date())
        if nd is not None:
            out[nd] = row
    return pd.DataFrame(out).T


def predictive(sig_next, bars):
    day = bars.groupby(bars.index.date).agg(o=("Open", "first"), c=("Close", "last"))
    day["ret"] = np.sign(day.c - day.o)                    # next day's open -> close direction
    res = {}
    for col in sig_next.columns:
        j = pd.concat([sig_next[col], day.ret], axis=1, join="inner").dropna()
        j = j[j.iloc[:, 0] != 0]
        tr = j[pd.to_datetime(j.index) <= R.TRAIN_END]; te = j[pd.to_datetime(j.index) > R.TRAIN_END]
        hit = lambda x: round(100 * (x.iloc[:, 0] == x.iloc[:, 1]).mean(), 1) if len(x) else None
        res[col] = dict(train_hit=hit(tr), test_hit=hit(te), days=len(j))
    return res


_df = _tr = _p = _el = _es = None


def _init():
    global _df, _tr, _p, _el, _es
    T._init()
    df = add_signals_v2(AF._b, "st_ema", "none", st=(10, 3.0))
    f = AF.filt("30m EMA 9/21", df)
    df["bull"] &= f[0]; df["bear"] &= f[1]
    _df = df
    _el, _es = E.exit_arrays(df, "30m EMA 9/21 flips")


def run(args):
    name, bias_by_day, mode = args
    df = _df.copy()
    if name != "No participant filter (current)":
        b = np.array([bias_by_day.get(d, 0) for d in df.index.date])
        if mode == "filter":                 # trade only in the bias direction, skip neutral days
            df["bull"] &= b > 0; df["bear"] &= b < 0
    p = replace(R.mk(**V.BASE), max_trades=1, fresh=False, sl=100000.0, lots=6)
    tr = backtest(df, AF._v, p)
    r = E.simulate(df, tr, replace(p, squareoff=time(15, 0)), _el, _es, 18000)
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    return dict(name=name, train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]), all=R.stats(r),
                years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()},
                days_traded=int(r.entry_ts.dt.date.nunique()))


def main():
    AF._init()
    bars = AF._b
    days = sorted(set(bars.index.date))
    sig = signals()
    nxt = next_day_map(sig, days)
    pred = predictive(nxt, bars)
    jobs = [("No participant filter (current)", {}, "none")] + [(c, nxt[c].to_dict(), "filter") for c in nxt.columns]
    with Pool(4, initializer=_init) as pool:
        strat = pool.map(run, jobs)
    (R.OUT / "participant.json").write_text(json.dumps(dict(predictive=pred, strategy=strat), indent=1, default=str))
    print("Next-day direction hit rate (open->close), % of days the bias was right:")
    for k, v in pred.items():
        print(f"  {k:46} train {v['train_hit']}%  test {v['test_hit']}%  ({v['days']} days)")
    print("\nAs a filter on the strategy (6 lots, final rules):")
    for r in strat:
        print(f"  {r['name']:46} | train {r['train']['net']:>9} test {r['test']['net']:>9} all {r['all']['net']:>9} "
              f"dd {r['all']['dd']:>9} pf {r['all']['pf']} | days {r['days_traded']} | {r['years']}")


if __name__ == "__main__":
    main()
