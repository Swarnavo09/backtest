"""Which indicator-vs-indicator rule best replaces 'ADX(14) > 30' (for platforms with no Number/Constant)?
Encodes each rule into the 'adx' column (100 = pass, 0 = fail) so cs_lab's 'adx > 50' check applies it."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import run_refined  # noqa  (refined config)
import run_final as R
from bt import common as C
from bt.cs_lab import Lab
from research.refine_grid import stat

def dmi(b, n=14):
    up, dn = b.High.diff(), -b.Low.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), b.index); ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), b.index)
    tr = C.atr(b, n); return 100 * C.rma(pdm, n) / tr, 100 * C.rma(ndm, n) / tr

class SubLab(Lab):
    rule = "adx>30"
    def tf(self, minutes, st_period=10, st_mult=3.0, adx_period=14):
        key = (minutes, st_period, st_mult, adx_period, self.rule)
        if key not in self._tf:
            b = super().tf(minutes, st_period, st_mult, adx_period).copy()
            if minutes == 15:
                adx, adx28 = C.adx(b, 14), C.adx(b, 28)
                pdi, ndi = dmi(b, 14)
                d = b["dir"]
                ok = {"adx>30": adx > 30,
                      "none": pd.Series(True, b.index),
                      "DI agrees (+DI>-DI long, -DI>+DI short)": ((d == 1) & (pdi > ndi)) | ((d == -1) & (ndi > pdi)),
                      "ADX(14) > ADX(28)": adx > adx28,
                      "ADX > both DI lines": (adx > pdi) & (adx > ndi),
                      "DI agrees AND ADX > weaker DI": (((d == 1) & (pdi > ndi) & (adx > ndi)) | ((d == -1) & (ndi > pdi) & (adx > pdi))),
                      }[self.rule]
                b["adx"] = np.where(ok, 100.0, 0.0)
            self._tf[key] = b
        return self._tf[key]

df = C.load_1m(); df = df[df.index >= "2018-09-01"]
rows = []
for rule in ["adx>30", "none", "DI agrees (+DI>-DI long, -DI>+DI short)", "ADX(14) > ADX(28)", "ADX > both DI lines", "DI agrees AND ADX > weaker DI"]:
    lab = SubLab(df); lab.rule = rule
    cfg = dict(R.FINAL, adx_min=50)
    a, b = stat(lab.run(15, *R.DEV, **cfg)), stat(lab.run(15, R.START, R.END, **cfg))
    rows.append(dict(rule=rule, dev_n=a["n"], dev_pf=round(a["pf"], 2), dev_per_yr=round(a["per_yr"]), test_n=b["n"], test_win=round(b["win"], 1), test_pf=round(b["pf"], 2), test_net_2y=round(b["net"])))
    print(rows[-1], flush=True)
pd.DataFrame(rows).to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "adx_substitutes.csv"), index=False)
