"""Fixed (non-optimised) improvement ideas, judged on all 3 years, recent windows and rolling 3-month stability."""
import pandas as pd, numpy as np
from weekly_combined import *
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
# extra features
up=df.High.diff(); dn=-df.Low.diff()
pdm=np.where((up>dn)&(up>0),up,0.0); mdm=np.where((dn>up)&(dn>0),dn,0.0)
tr_=pd.concat([df.High-df.Low,(df.High-df.Close.shift()).abs(),(df.Low-df.Close.shift()).abs()],axis=1).max(axis=1)
atr14=tr_.ewm(alpha=1/14,adjust=False).mean()
pdi=100*pd.Series(pdm,df.index).ewm(alpha=1/14,adjust=False).mean()/atr14; mdi=100*pd.Series(mdm,df.index).ewm(alpha=1/14,adjust=False).mean()/atr14
adx=(100*(pdi-mdi).abs()/(pdi+mdi)).ewm(alpha=1/14,adjust=False).mean()
vix=VIX.reindex(df.index.normalize(),method="ffill").shift(0).values
dclose=df.Close.groupby(df.index.normalize()).last()
d50=(dclose>dclose.ewm(span=50,adjust=False).mean()).shift().reindex(df.index.normalize()).fillna(False).astype(bool).values
d20=df.d_up.values
L0,S0=signals(df)
fresh_l=L0&~np.roll(L0,1); fresh_s=S0&~np.roll(S0,1)
V={"V0 current rules":None,
   "V1 + daily trend (EMA20)":lambda d:(d20,~d20),
   "V2 + daily trend (EMA50)":lambda d:(d50,~d50),
   "V3 + ADX(14) > 20":lambda d:((adx>20).values,(adx>20).values),
   "V4 + VIX <= 18":lambda d:(vix<=18,vix<=18),
   "V5 fresh signal only":lambda d:(fresh_l,fresh_s),
   "V6 daily EMA20 + ADX>20":lambda d:(d20&(adx>20).values,~d20&(adx>20).values),
   "V7 daily EMA50 + ADX>20":lambda d:(d50&(adx>20).values,~d50&(adx>20).values)}
EX={"exits A: SL8k TP40k lock2R, Thu/Fri":dict(sl_rs=8000,tp_rs=40000,lock=(16000,300,1600,1600),cap=2,entry_days=(2,3)),
    "exits B: SL8k TP40k lock2R, any day":dict(sl_rs=8000,tp_rs=40000,lock=(16000,300,1600,1600),cap=2,entry_days=(1,2,3,4))}
rows=[]
for en,ex in EX.items():
    for vn,f in V.items():
        tr=run(df,60,E,co,pin,ex["sl_rs"],ex["tp_rs"],ex["lock"],ex["cap"],ex["entry_days"],"exp",True,filt=f)
        r={"exits":en[:8],"variant":vn}
        for k,(a,b) in YRS.items(): r[k]=evw(tr[(tr.entry_time>=a)&(tr.entry_time<b)])["net"]
        for lab,st in [("6m","2026-05-20"),("3m","2026-08-20")]: r[lab]=round(tr[tr.entry_time>=st].net.sum())
        t2=tr[tr.entry_time>="2023-12-01"]; m=t2.set_index("exit_time").net.resample("ME").sum(); r3=m.rolling(3).sum().dropna()
        e=evw(tr[tr.entry_time>="2024-11-20"]); r.update(n2y=e["n"],net2y=e["net"],pf=e["pf"],dd2y=e["dd"],roll3m_pos=f"{(r3>0).sum()}/{len(r3)}",months_pos=f"{(m>0).sum()}/{len(m)}")
        rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",250); pd.set_option("display.max_columns",30); print(R.to_string(index=False)); R.to_csv("results/weekly_robust_variants.csv",index=False)
