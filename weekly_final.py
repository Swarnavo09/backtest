import pandas as pd, numpy as np
from weekly_combined import *
SL,TP,LOCK,CAP,ED,EM=8000,40000,(16000,300,1600,1600),2,(2,3),"exp"
for iv_,bar,a in [("60m",60,"2024-11-20"),("15m",15,"2026-08-28")]:
    df=indicators(load(iv_),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
    tr=run(df,bar,E,co,pin,SL,TP,LOCK,CAP,ED,EM,True)
    if iv_=="60m":
        for lab,(x,y) in dict(YRS).items(): print(lab,evw(tr[(tr.entry_time>=x)&(tr.entry_time<y)]))
        alt=run(df,bar,E,co,pin,SL,48000,LOCK,CAP,ED,EM,True); print("1:6 variant 2y",evw(alt[alt.entry_time>=a]))
        nolock=run(df,bar,E,co,pin,SL,TP,None,CAP,ED,EM,True); print("no lock 2y",evw(nolock[nolock.entry_time>=a]))
        noema=run(df,bar,E,co,pin,SL,TP,LOCK,CAP,ED,EM,False); print("no EMA exit 2y",evw(noema[noema.entry_time>=a]))
        c1=run(df,bar,E,co,pin,SL,TP,LOCK,1,ED,EM,True); print("cap1 2y",evw(c1[c1.entry_time>=a]))
    t=tr[tr.entry_time>=a].copy(); t["same_day"]=t.entry_time.dt.date==t.exit_time.dt.date
    weeks=t.cycle.nunique(); allweeks=len([e for e in E if pd.Timestamp(a)<=e<=days[-1]])
    print(f"\n== {iv_} since {a}:",evw(t),f"weeks traded {weeks}/{allweeks}")
    print(" exit reasons:",t.reason.value_counts().to_dict())
    print(" by entry weekday (n, win%, loss%, net):")
    for wd,g in t.groupby("entry_wd"): print("   ",["Mon","Tue","Wed","Thu","Fri","Sat"][wd],len(g),f"win {round((g.net>0).mean()*100)}%",f"loss {round((g.net<=0).mean()*100)}%",round(g.net.sum()))
    cur=t[t.entry_time>="2025-09-01"]
    print(" CURRENT Tuesday-expiry regime (since Sep-2025):",evw(cur))
    for wd,g in cur.groupby("entry_wd"): print("   ",["Mon","Tue","Wed","Thu","Fri","Sat"][wd],len(g),f"win {round((g.net>0).mean()*100)}%",f"loss {round((g.net<=0).mean()*100)}%",round(g.net.sum()))
    los=t[t.net<=0]; win=t[t.net>0]
    q=lambda s: s.describe(percentiles=[.25,.5,.75]).round(0)[["count","mean","25%","50%","75%"]].to_dict()
    print(" spot pts against on losers:",q(los.spot_move),"worst",round(los.spot_move.min()) if len(los) else None)
    print(" spot pts in favour on winners:",q(win.spot_move))
    print(" TP hits: spot pts",q(t[t.reason=="M2M_TP"].spot_move))
    print(" same-day",int(t.same_day.sum()),round(t[t.same_day].net.sum()),"| overnight",int((~t.same_day).sum()),round(t[~t.same_day].net.sum()))
    print(" avg loss",round(los.net.mean()),"avg win",round(win.net.mean()),"avg premium",round(t.prem.mean()),"avg spot",round(t.entry_spot.mean()))
    if iv_=="60m":
        pm=t.groupby(t.exit_time.dt.to_period("M")).net.sum(); print(" months +",(pm>0).sum(),"/",len(pm),"worst month",round(pm.min()))
        t.to_csv("results/trades_weekly_final.csv",index=False)
