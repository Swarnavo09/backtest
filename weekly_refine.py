import itertools, pandas as pd
from weekly_combined import *
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
P=dict(YRS,L2Y=("2024-11-20","2026-11-21")); rows=[]
for sl,rr,ed,em,lk in itertools.product([6500,8000,10000,12000],[5,6],[(1,2,3,4),(2,3,4),(2,3)],["pre","exp"],["none","2R"]):
    lock=(2*sl,300,sl/5,sl/5) if lk=="2R" else None
    tr=run(df,60,E,co,pin,sl,sl*rr,lock,2,ed,em,True)
    r=dict(sl=sl,tp=sl*rr,rr=rr,entry_days=str(ed),exit=em,lock=lk)
    for k,(a,b) in P.items():
        e=evw(tr[(tr.entry_time>=a)&(tr.entry_time<b)]); r.update({f"{k}_{f}":v for f,v in e.items()})
    rows.append(r)
R=pd.DataFrame(rows); R["min_year"]=R[["Y0_net","Y1_net","Y2_net"]].min(axis=1); R["score"]=R.L2Y_net/(-R.L2Y_dd)
pd.set_option("display.width",260); pd.set_option("display.max_columns",40)
print(R.sort_values("score",ascending=False).head(16)[["sl","tp","rr","entry_days","exit","lock","Y0_net","Y1_net","Y2_net","L2Y_n","L2Y_net","L2Y_pf","L2Y_dd","L2Y_win","min_year","score"]].to_string(index=False))
R.to_csv("results/weekly_refine_60m.csv",index=False)
