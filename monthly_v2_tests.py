import pandas as pd, numpy as np
from monthly_combined import *
dc=df.Close.groupby(df.index.normalize()).last()
d20=(dc>dc.ewm(span=20,adjust=False).mean()).shift().reindex(df.index.normalize()).fillna(False).astype(bool).values
d50=(dc>dc.ewm(span=50,adjust=False).mean()).shift().reindex(df.index.normalize()).fillna(False).astype(bool).values
base_f=FILT["VIX<=18+PDH/PDL"]
def f_trend(dd,arr):
    L,S=base_f(dd); return L&arr, S&~arr
B=dict(sl_rs=6500,tp_rs=32500,lock=(13000,300,1300,1300),cap=99,entry_days=(),exit_mode="exp",ema_exit=False,kill=False,exit_before=1,no_entry_last=3,kstart=2,filt=base_f,skip_wd=(0,))
V={"v1 (current Tradetron)":{},
   "skip Mon+Wed":dict(skip_wd=(0,2)),
   "no re-entry same day":dict(no_same_day=True),
   "long only above daily EMA20 (short below)":dict(filt=lambda dd:f_trend(dd,d20)),
   "long only above daily EMA50 (short below)":dict(filt=lambda dd:f_trend(dd,d50)),
   "skip Wed + no same-day re-entry":dict(skip_wd=(0,2),no_same_day=True),
   "skip Wed + no same-day + EMA20 trend":dict(skip_wd=(0,2),no_same_day=True,filt=lambda dd:f_trend(dd,d20)),
   "no same-day + EMA20 trend":dict(no_same_day=True,filt=lambda dd:f_trend(dd,d20))}
rows=[]
for k,v in V.items():
    tr=run(df,60,E,co,pin,**dict(B,**v))
    r={"variant":k}
    for y,(a,b) in YRS.items(): r[y]=round(tr[(tr.entry_time>=a)&(tr.entry_time<b)].net.sum())
    r["2026 Apr-Oct"]=round(tr[(tr.entry_time>="2026-04-01")&(tr.entry_time<"2026-10-18")].net.sum())
    t=tr[tr.entry_time>="2024-11-20"]; e=evw(t); m=t.set_index("exit_time").net.resample("ME").sum()
    r.update(trades_2y=e["n"],per_month=round(e["n"]/24,1),net_2y=e["net"],pf=e["pf"],maxdd=e["dd"],worst_month=round(m.min()),months_pos=f"{(m>0).sum()}/{len(m)}")
    rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",260); print(R.to_string(index=False)); R.to_csv("results/monthly_v2_tests.csv",index=False)
