"""Monthly synthetic futures (monthly ATM CE buy + PE sell), per-leg SL/trail, no overall M2M.
Grid for trade frequency, then deep stats for the chosen setup."""
import itertools, sys, pandas as pd, numpy as np
from synthetic_legs import *
iv_=sys.argv[1] if len(sys.argv)>1 else "60m"; bar=60 if iv_=="60m" else 15
df=indicators(load(iv_),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize())))
cyc=make_cycles(days,"monthly")
P=dict(YRS,L2Y=("2024-11-20","2026-11-21")) if bar==60 else {"W":("2026-08-28","2026-11-21")}
months=24 if bar==60 else 2.8
rows=[]
for sl,trail,cap in itertools.product([15,20,25,30],[None,(30,15),(40,20)],[4,6,8,10,15,99]):
    tr=simulate(df,bar,cyc,sl,0,trail,cap)
    r=dict(leg_sl=sl,trail=str(trail),max_cycle=cap if cap<99 else "unl")
    for k,(a,b) in P.items():
        e=evn(tr[(tr.entry_time>=a)&(tr.entry_time<b)]); r.update({f"{k}_{f}":v for f,v in e.items()})
    key="L2Y" if bar==60 else "W"; t2=tr[(tr.entry_time>=P[key][0])]
    m=t2.groupby(t2.entry_time.dt.to_period("M")).size()
    r["trades_per_month"]=round(len(t2)/months,1); r["months_lt4"]=int((m<4).sum()) if bar==60 else None
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv(f"results/monthly_synth_legs_{iv_}.csv",index=False)
pd.set_option("display.width",250); pd.set_option("display.max_columns",30)
if bar==60:
    R["min_year"]=R[["Y0_net","Y1_net","Y2_net"]].min(axis=1); R["score"]=R.L2Y_net/(-R.L2Y_dd).clip(lower=1)
    print(R[(R.min_year>0)].sort_values("score",ascending=False).head(15).to_string(index=False))
else:
    print(R.sort_values("W_net",ascending=False).head(15).to_string(index=False))
