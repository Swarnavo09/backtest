"""Overall loss limit (INR) for 2 and 3 lots, 30-min EMA filter, no trailing.

    python run_sl_lots.py   -> results/sl_lots.json
"""
import json
from dataclasses import replace
from multiprocessing import Pool

import run_ar_filters as AF
import run_trailing as T
import run_v2 as R


def job(args):
    lots, loss = args
    T._init()
    df, tr, p = T.entries("30m EMA 9/21")
    p = replace(p, lots=lots)
    T.LOSS = loss
    r = T.simulate(df, tr, p, "none", {})
    d = r.entry_ts.dt.strftime("%Y-%m-%d")
    sl = r[r.reason == "sl"]
    return dict(lots=lots, loss=loss, train=R.stats(r[d <= R.TRAIN_END]), test=R.stats(r[d > R.TRAIN_END]),
                all=R.stats(r), sl_hits=len(sl), sl_pct=round(100 * len(sl) / len(r), 1),
                avg_sl=round(sl.net.mean()) if len(sl) else 0, worst=round(r.net.min()),
                years={int(k): round(v) for k, v in r.groupby(r.entry_ts.dt.year).net.sum().items()})


def main():
    jobs = [(2, x) for x in (4000, 5000, 6000, 7000, 8000)] + [(3, x) for x in (6000, 7500, 9000, 10500, 12000)]
    with Pool(4) as pool:
        res = pool.map(job, jobs)
    (R.OUT / "sl_lots.json").write_text(json.dumps(res, indent=1, default=str))
    for r in res:
        print(f"{r['lots']} lots SL {r['loss']:>6} | all {r['all']['net']:>9} dd {r['all']['dd']:>8} | train {r['train']['net']:>8} "
              f"test {r['test']['net']:>8} pf {r['test']['pf']} | SL hit {r['sl_pct']}% avg {r['avg_sl']} worst {r['worst']} | {r['years']}")


if __name__ == "__main__":
    main()
