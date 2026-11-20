import itertools, pandas as pd
from nifty_fut_bt import *
df = indicators(load("60m"), htf_mult=2)
IS = ("2024-11-20","2025-11-19"); OOS=("2025-11-20","2026-11-21"); OLD=("2023-12-01","2024-11-19"); FULL=("2024-11-20","2026-11-21")
base = dict(bar_min=60, start=570, no_trade_after=900, sq_off=910, max_trades=1, days=[0,1,3],
            vol=0, vwap=False, sl=1.0, rr=2, sig_exit=True)
def run(p, per):
    tr = backtest(df, p); 
    if tr.empty: return tr
    return tr[(tr.entry_time>=per[0])&(tr.entry_time<per[1])]
print("BASELINE (your conditions, Mon/Tue/Thu, SL 1xATR, 1:2)")
for name,per in [("IS",IS),("OOS",OOS),("FULL2y",FULL),("OLD",OLD)]:
    print(name, stats(run(base,per)))
rows=[]
grid = dict(days=[[0,1,3],[0,1,2,3,4]], vol=[0,1.0,1.2], vwap=[False,True], sl=[0.75,1.0,1.5,"st"],
            rr=[2,3,4], sig_exit=[True,False], max_trades=[1,2])
keys=list(grid)
for vals in itertools.product(*grid.values()):
    p = dict(base, **dict(zip(keys,vals)))
    tr = backtest(df,p)
    r = dict(zip(keys,vals)); r["days"]="MTT" if len(r["days"])==3 else "All"
    for name,per in [("IS",IS),("OOS",OOS),("OLD",OLD)]:
        s = stats(tr[(tr.entry_time>=per[0])&(tr.entry_time<per[1])])
        r[name+"_n"]=s.get("trades",0); r[name+"_rs"]=s.get("net_rs",0); r[name+"_pf"]=s.get("pf",0); r[name+"_dd"]=s.get("maxdd_rs",0); r[name+"_win"]=s.get("win",0)
    rows.append(r)
R=pd.DataFrame(rows); R.to_csv("results/grid_60m.csv",index=False)
pd.set_option("display.width",250); pd.set_option("display.max_columns",40)
print("\nTop 15 by IN-SAMPLE net (then see OOS):")
print(R[R.IS_n>=25].sort_values("IS_rs",ascending=False).head(15).to_string())
print("\nShare of configs profitable: IS",(R.IS_rs>0).mean().round(2)," OOS",(R.OOS_rs>0).mean().round(2)," OLD",(R.OLD_rs>0).mean().round(2))
print("Configs profitable in all 3 years:", ((R.IS_rs>0)&(R.OOS_rs>0)&(R.OLD_rs>0)).sum(), "of", len(R))
for k in ["days","vol","vwap","sl","rr","sig_exit","max_trades"]:
    print(R.groupby(k)[["IS_rs","OOS_rs","OLD_rs"]].median().round(0).to_string(),"\n")
