"""Honest test: walk-forward. Each month, pick the best weekly settings using ONLY the previous 12 months,
then trade the next month with them. Compare with the settings I picked using all data (in-sample)."""
import itertools, pickle, pandas as pd, numpy as np
from weekly_combined import *
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
grid=list(itertools.product([5000,6500,8000,10000],[3,4,5,6],["none","2R"],[(1,2,3),(2,3),(1,2,3,4),(2,3,4)],["pre","exp"],[True,False]))
res={}
for g in grid:
    sl,rr,lk,ed,em,ema=g; lock=(2*sl,300,sl/5,sl/5) if lk=="2R" else None
    tr=run(df,60,E,co,pin,sl,sl*rr,lock,2,ed,em,ema)
    res[str(g)]=tr.set_index("exit_time").net.resample("ME").sum() if len(tr) else pd.Series(dtype=float)
M=pd.DataFrame(res).fillna(0.0); M.index=M.index.to_period("M")
pickle.dump(M,open("results/wf_monthly.pkl","wb"))
test_months=[p for p in M.index if p>=pd.Period("2024-12","M")]
out=[]
for p in test_months:
    train=M[(M.index>=p-12)&(M.index<p)]
    if len(train)<9: continue
    score=train.sum()/(-(train.cumsum()-train.cumsum().cummax()).min()).clip(lower=5000)   # return / drawdown
    best=score.idxmax(); out.append(dict(month=str(p),pick=str(best),pnl=M.loc[p,best]))
W=pd.DataFrame(out); W.to_csv("results/walkforward_weekly.csv",index=False)
insample=str((8000,5,"2R",(2,3),"exp",True))
def summ(s):
    eq=s.cumsum(); return dict(total=round(s.sum()),dd=round((eq-eq.cummax()).min()),months_pos=f"{(s>0).sum()}/{len(s)}")
wf=W.set_index("month").pnl
print("WALK-FORWARD (honest) :",summ(wf))
print("IN-SAMPLE pick        :",summ(M.loc[[pd.Period(m,'M') for m in W.month],insample]))
for lab,n in [("last 1m",1),("last 3m",3),("last 6m",6),("last 12m",12)]:
    print(f"  {lab}: walk-forward {round(wf.tail(n).sum())}  | in-sample pick {round(M[insample].tail(n).sum())}")
print("median config over same months:",summ(M.loc[[pd.Period(m,'M') for m in W.month]].median(axis=1)))
print("share of configs profitable in last 12m:",round((M.tail(12).sum()>0).mean()*100),"%  last 6m:",round((M.tail(6).sum()>0).mean()*100),"%")
print(W.tail(12).to_string(index=False))
