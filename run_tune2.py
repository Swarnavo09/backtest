"""Day-selection variants (expiry day, day before expiry, weekday skips) +/- 1H Supertrend, 4 and 6 lots."""
import bisect, json
from datetime import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import run_tune as U
import run_v2 as R


def daymask(rule):
    df = U._G["base"]
    ed = U._G["expday"]
    dates = df.index.date
    import realiv
    rv = realiv.install("mix70v")
    days = rv.days
    pos = {d: i for i, d in enumerate(days)}
    # day before expiry: next trading day is an expiry day
    nxt_is_exp = np.array([(pos.get(d) is not None and pos[d] + 1 < len(days) and
                            days[pos[d] + 1] in set(rv.expiries)) for d in dates])
    wd = df.index.weekday
    if rule == "all days": return np.ones(len(df), bool)
    if rule == "expiry day only": return ed
    if rule == "expiry day + day before": return ed | nxt_is_exp
    if rule == "skip Wednesday": return wd != 2
    if rule == "skip Mon+Wed": return ~np.isin(wd, [0, 2])
    if rule == "skip day after expiry": 
        prev_is_exp = np.array([(pos.get(d) is not None and pos[d] > 0 and days[pos[d] - 1] in set(rv.expiries)) for d in dates])
        return ~prev_is_exp
    raise ValueError(rule)


RULES = ["all days", "expiry day only", "expiry day + day before", "skip Wednesday", "skip Mon+Wed", "skip day after expiry"]


def job(args):
    rule, filt, last, lots = args
    df0 = U._G["base"]
    m = daymask(rule)
    save = U._G["base"]
    df = df0.copy(); df["bull"] &= m; df["bear"] &= m
    U._G["base"] = df
    try:
        r = U.simulate(filt, time(9, 30), last, None, lots)
    finally:
        U._G["base"] = save
    s = U.summ(r)
    return dict(rule=rule, filter=filt, last=last.strftime("%H:%M"), lots=lots, **s)


def main():
    jobs = [(r, f, l, lots) for r in RULES for f in ("none", "1H Supertrend") for l in (time(13, 30), time(12, 30)) for lots in (4, 6)]
    with Pool(4, initializer=U._init) as pool:
        res = pool.map(job, jobs)
    (R.OUT / "tune2.json").write_text(json.dumps(res, indent=1, default=str))
    for lots in (4, 6):
        print(f"\n=== {lots} lots")
        for r in sorted([r for r in res if r["lots"] == lots], key=lambda r: -r["train"]["net"] / (1 + abs(r["train"]["dd"]) / 50000)):
            print(f"{r['rule']:24} {r['filter']:13} last {r['last']} | trades {r['all']['n']:4} | train {r['train']['net']:>8} (dd {r['train']['dd']:>8}) "
                  f"test {r['test']['net']:>8} (dd {r['test']['dd']:>8}) | all {r['all']['net']:>9} dd {r['all']['dd']:>9} pf {r['all']['pf']} win {r['all']['win']} | last12 {r['last12']:>8} | {r['years']}")


if __name__ == "__main__":
    main()
