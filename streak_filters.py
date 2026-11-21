"""Filters aimed at fewer consecutive losses (1H, 3 years, correct cycle days 2-3, combined SL 8k / TP 40k / lock 2R)."""
import pandas as pd, numpy as np
from weekly_combined import *
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
vix=VIX.reindex(df.index.normalize(),method="ffill").values
L0,S0=signals(df); fl=L0&~np.roll(L0,1); fs=S0&~np.roll(S0,1)
dh=df.High.groupby(df.index.normalize()).max(); dl=df.Low.groupby(df.index.normalize()).min()
pdh=dh.shift().reindex(df.index.normalize()).values; pdl=dl.shift().reindex(df.index.normalize()).values
c=df.Close.values; tmin=(df.index.hour*60+df.index.minute).values+60
do=df.Open.groupby(df.index.normalize()).transform("first").values; pc=df.Close.groupby(df.index.normalize()).last().shift().reindex(df.index.normalize()).values
gap=np.abs(do-pc)
T=np.ones(len(df),bool)
F={"base (Thu/Fri now)":None,
   "VIX <= 18":lambda d:(vix<=18,vix<=18),
   "fresh signal":lambda d:(fl,fs),
   "VIX<=18 + fresh":lambda d:(fl&(vix<=18),fs&(vix<=18)),
   "close beyond prev-day high/low":lambda d:(c>pdh,c<pdl),
   "VIX<=18 + prev-day breakout":lambda d:((c>pdh)&(vix<=18),(c<pdl)&(vix<=18)),
   "skip first candle (enter from 11:15)":lambda d:(tmin>=675,tmin>=675),
   "no entries after 14:15":lambda d:(tmin<=855,tmin<=855),
   "skip gap days (open gap > 100 pts)":lambda d:(gap<=100,gap<=100),
   "VIX<=18 + no gap>100":lambda d:((vix<=18)&(gap<=100),(vix<=18)&(gap<=100))}
def streak(n):
    s=(n<=0).astype(int); return int(s.groupby((s!=s.shift()).cumsum()).sum().max()) if len(n) else 0
rows=[]
for k,f in F.items():
    tr=run(df,60,E,co,pin,8000,40000,(16000,300,1600,1600),2,(2,3),"exp",True,filt=f)
    t=tr[tr.entry_time>="2023-12-01"]; r={"filter":k}
    for y,(a,b) in YRS.items(): r[y]=round(tr[(tr.entry_time>=a)&(tr.entry_time<b)].net.sum())
    r["6-12m ago"]=round(tr[(tr.entry_time>="2025-11-21")&(tr.entry_time<"2026-05-21")].net.sum()); r["last 6m"]=round(tr[tr.entry_time>="2026-05-21"].net.sum())
    e=evw(t); m=t.set_index("exit_time").net.resample("ME").sum()
    r.update(trades_3y=e["n"],net_3y=e["net"],pf=e["pf"],maxdd=e["dd"],win=e["win"],max_loss_streak=streak(t.net.reset_index(drop=True)),months_pos=f"{(m>0).sum()}/{len(m)}")
    rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",260); pd.set_option("display.max_columns",30); print(R.to_string(index=False)); R.to_csv("results/weekly_streak_filters.csv",index=False)
# replicate Algorooms literal weekday ticks (Thu/Fri every period) to show the cycle-day effect
lit=lambda d:(np.isin(df.index.dayofweek,[3,4]),np.isin(df.index.dayofweek,[3,4]))
tr=run(df,60,E,co,pin,8000,40000,(16000,300,1600,1600),2,(1,2,3,4,5),"exp",True,filt=lit)
print("\nLiteral THU/FRI ticks (what Algorooms did):",{y:round(tr[(tr.entry_time>=a)&(tr.entry_time<b)].net.sum()) for y,(a,b) in YRS.items()},
      "| before Sep-25:",round(tr[tr.entry_time<"2025-09-01"].net.sum()),"since:",round(tr[tr.entry_time>="2025-09-01"].net.sum()))
