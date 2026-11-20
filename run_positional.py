import itertools, pandas as pd, numpy as np
from nifty_fut_bt import *
P = {"IS":("2024-11-20","2025-11-19"),"OOS":("2025-11-20","2026-11-21"),"OLD":("2023-12-01","2024-11-19")}
base = dict(bar_min=60, start=570, no_trade_after=900, sq_off=10**6, max_trades=1, days=[0,1,2,3,4],
            vol=0, vwap=False, sl="pts", sl_pts=40, rr=2, sig_exit=True)
grid = dict(htf=[2,6], mode=["state","fresh","pullback"], vol=[0,1.2], vwap=[False,True],
            sl_pts=[30,40,50,60], rr=[2,3,4,5], sig_exit=[True,False], be=[False,True])
dfs = {m: indicators(load("60m"), m) for m in grid["htf"]}
rows=[]
for vals in itertools.product(*grid.values()):
    r=dict(zip(grid,vals))
    if r["mode"]=="pullback" and r["vwap"]: continue
    p=dict(base,**r); tr=backtest(dfs[r["htf"]],p)
    for k,(a,b) in P.items():
        s=stats(tr[(tr.entry_time>=a)&(tr.entry_time<b)] if len(tr) else tr)
        for f in ["trades","net_rs","pf","maxdd_rs","win"]: r[f"{k}_{f}"]=s.get(f,0)
    t2=tr[tr.entry_time>="2024-11-20"]
    r["2y_rs"]=round(t2.net.sum()*LOT); r["2y_gross"]=round(t2.pts.sum()*LOT); r["2y_n"]=len(t2)
    r["avg_hold_h"]=round(((t2.exit_time-t2.entry_time).dt.total_seconds()/3600).mean(),1) if len(t2) else 0
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv("results/grid_positional_60m.csv",index=False)
pd.set_option("display.width",260); pd.set_option("display.max_columns",40)
print("configs:",len(R)," 2y net>0:",(R["2y_rs"]>0).sum()," 2y gross>0:",(R["2y_gross"]>0).sum(),
      " profitable all 3 yrs:",((R.IS_net_rs>0)&(R.OOS_net_rs>0)&(R.OLD_net_rs>0)).sum())
for k in grid: print(R.groupby(k)[["IS_net_rs","OOS_net_rs","OLD_net_rs","2y_rs"]].median().round(0).to_string(),"\n")
cols=["htf","mode","vol","vwap","sl_pts","rr","sig_exit","be","IS_trades","IS_net_rs","IS_pf","OOS_trades","OOS_net_rs","OOS_pf","OLD_net_rs","2y_rs","2y_n","avg_hold_h"]
print("Top by IS (selected only on year 1):"); print(R[R.IS_trades>=30].sort_values("IS_net_rs",ascending=False)[cols].head(12).to_string())
