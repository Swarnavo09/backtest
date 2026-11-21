import itertools, pandas as pd
from spreads import *
df=indicators(load("60m"),2); rows=[]
G=[("weekly",m,off,w,tp,sl,mn,mx,vx) for m in ["neutral"] for off in [100,150] for w in [300,400] for tp in [0.6,0.7,0.8] for sl in [1.5,2.0] for (mn,mx) in [(1,6),(2,6),(3,6)] for vx in [99,18]]
G+=[("monthly",m,off,w,tp,sl,mn,mx,vx) for m in ["neutral","trend"] for off in [200,300,400] for w in [300,500] for tp in [0.5,0.7] for sl in [1.0,1.5,2.0] for (mn,mx) in [(5,30),(10,25)] for vx in [99,18]]
for kind,m,off,w,tp,sl,mn,mx,vx in G:
    tr=run_spread(df,kind,m,off,w,tp,sl,mn,mx,(615,900),0,False,vx)
    t2=tr[tr.entry>="2024-11-20"] if len(tr) else tr
    r=dict(kind=kind,mode=m,short_off=off,width=w,tp=tp,sl=sl,min_dte=mn,vix_max=vx)
    for y,(a,b) in YRS.items(): r[y]=round(tr[(tr.entry>=a)&(tr.entry<b)].pnl.sum()) if len(tr) else 0
    r.update(stats(t2)); rows.append(r)
pd.DataFrame(rows).to_csv("results/spreads_grid2.csv",index=False)
