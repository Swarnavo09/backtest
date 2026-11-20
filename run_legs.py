import sys, itertools, pandas as pd
from synthetic_legs import *
iv_ = sys.argv[1] if len(sys.argv)>1 else "60m"
df=indicators(load(iv_),2); bar=60 if iv_=="60m" else 15
days=pd.DatetimeIndex(sorted(set(df.index.normalize())))
cyc=make_cycles(days,"biweekly")
rows=[]
P = dict(YRS,L2Y=("2024-11-20","2026-11-21")) if bar==60 else {"15m_window":("2026-08-28","2026-11-21")}
grid=list(itertools.product([15,20,25,30],[0,75,100,150],[None,(40,20),(50,50)],[2,3,5,99]))
for sl,tp,tr_,cap in grid:
    tr=simulate(df,bar,cyc,sl,tp,tr_,cap)
    r=dict(leg_sl=sl,leg_tp=tp or "none",trail=str(tr_),max_cycle=cap if cap<99 else "unl")
    for k,(a,b) in P.items():
        e=evn(tr[(tr.entry_time>=a)&(tr.entry_time<b)] if len(tr) else tr)
        for f,v in e.items(): r[f"{k}_{f}"]=v
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv(f"results/biweekly_synthetic_legs_{iv_}.csv",index=False)
pd.set_option("display.width",250); pd.set_option("display.max_columns",30)
if bar==60:
    R["min_year"]=R[["Y0_net","Y1_net","Y2_net"]].min(axis=1); R["score"]=R.L2Y_net/(-R.L2Y_dd).clip(lower=1)
    print("all-years-profitable:",(R.min_year>0).sum(),"/",len(R))
    print(R[R.min_year>0].sort_values("score",ascending=False).head(15).to_string(index=False))
else:
    print(R.sort_values("15m_window_net",ascending=False).head(10).to_string(index=False))
