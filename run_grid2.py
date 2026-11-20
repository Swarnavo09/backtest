import itertools, sys, pandas as pd
from nifty_fut_bt import *
iv = sys.argv[1] if len(sys.argv)>1 else "60m"
df = indicators(load("60m"), htf_mult=2)
P = {"IS":("2024-11-20","2025-11-19"),"OOS":("2025-11-20","2026-11-21"),"OLD":("2023-12-01","2024-11-19")}
base = dict(bar_min=60, start=570, no_trade_after=900, sq_off=910, max_trades=1, days=[0,1,3], vol=0, vwap=False, sl=1.0, rr=2, sig_exit=True)
grid = dict(mode=["state","fresh","pullback"], daily=[False,True], days=[[0,1,3],[0,1,2,3,4]], vol=[0,1.0,1.2], vwap=[False,True],
            sl=[0.75,1.0,"st"], rr=[2,3], max_trades=[1,2])
rows=[]
for vals in itertools.product(*grid.values()):
    p=dict(base,**dict(zip(grid,vals)))
    if p["mode"]=="pullback" and p["vwap"]: continue
    tr=backtest(df,p); r=dict(zip(grid,vals)); r["days"]="MTT" if len(r["days"])==3 else "All"
    for k,(a,b) in P.items():
        s=stats(tr[(tr.entry_time>=a)&(tr.entry_time<b)] if len(tr) else tr)
        for f in ["trades","net_rs","pf","maxdd_rs","win"]: r[f"{k}_{f}"]=s.get(f,0)
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv("results/grid2_60m.csv",index=False)
pd.set_option("display.width",250); pd.set_option("display.max_columns",40)
R["min_pf"]=R[["IS_pf","OOS_pf","OLD_pf"]].min(axis=1)
print("profitable all 3 yrs:",((R.IS_net_rs>0)&(R.OOS_net_rs>0)&(R.OLD_net_rs>0)).sum(),"/",len(R))
print(R.groupby(["mode","daily"])[["IS_net_rs","OOS_net_rs","OLD_net_rs"]].median().round(0))
print(R[R.IS_trades>=25].sort_values("IS_pf",ascending=False).head(12).to_string())
print(R[(R.IS_trades>=25)&(R.OOS_trades>=25)].sort_values("min_pf",ascending=False).head(12).to_string())
