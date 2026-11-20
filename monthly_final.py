import pandas as pd, numpy as np
from synthetic_legs import *
def cyc_freeze(days, n):          # exit / freeze n trading days before monthly expiry
    c=make_cycles(days,"monthly"); ed={}
    for e in c["expiries"]:
        prev=days[days<e]; ed[e]=prev[-n] if len(prev)>=n else e
    c["exit_day"]=ed; return c
SL,TR,CAP=25,(30,15),8
out=[]
for iv_,bar in [("60m",60),("15m",15)]:
    df=indicators(load(iv_),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize())))
    per = dict(YRS,L2Y=("2024-11-20","2026-11-21")) if bar==60 else {"15m 28Aug-20Nov":("2026-08-28","2026-11-21")}
    for lab,n,skip in [("Base: exit 1 day before expiry",1,()),("Freeze last 3 days",3,()),("Skip Monday",1,(0,)),("Freeze 3 + skip Monday",3,(0,)),
                       ("Skip Friday",1,(4,)),("Skip Tuesday",1,(1,)),("Freeze last 2 days",2,())]:
        tr=simulate(df,bar,cyc_freeze(days,n),SL,0,TR,CAP,skip_wd=skip)
        r={"data":iv_,"rule":lab}
        for k,(a,b) in per.items():
            e=evn(tr[(tr.entry_time>=a)&(tr.entry_time<b)]); r.update({f"{k}_{f}":v for f,v in e.items()})
        out.append(r)
        if iv_=="60m" and lab.startswith("Base"): base60=tr
        if iv_=="15m" and lab.startswith("Base"): base15=tr
R=pd.DataFrame(out); pd.set_option("display.width",260); pd.set_option("display.max_columns",30); print(R.to_string(index=False))
R.to_csv("results/monthly_synth_skip_rules.csv",index=False)
for name,tr,a in [("1H 2y",base60,"2024-11-20"),("15m window",base15,"2026-08-28")]:
    t=tr[tr.entry_time>=a].copy(); t["same_day"]=t.entry_time.dt.date==t.exit_time.dt.date
    los=t[t.net<=0]; win=t[t.net>0]; sl_all=t[t.reasons=="SL/SL"]
    print(f"\n== {name}: trades {len(t)}, per month {len(t)/(24 if name.startswith('1H') else 2.8):.1f}")
    print(" losing trades:",len(los),"avg loss",round(los.net.mean()),"| winners:",len(win),"avg win",round(win.net.mean()))
    print(" spot pts AGAINST when stop hit (both legs SL, first leg):", sl_all.spot_move_first.describe(percentiles=[.25,.5,.75]).round(0)[["count","mean","25%","50%","75%","min"]].to_dict())
    print(" spot pts IN FAVOUR at exit for winners:", win.spot_move_last.describe(percentiles=[.25,.5,.75]).round(0)[["count","mean","25%","50%","75%","max"]].to_dict())
    print(" same-day trades:",int(t.same_day.sum()),"net",round(t[t.same_day].net.sum()),"| overnight:",int((~t.same_day).sum()),"net",round(t[~t.same_day].net.sum()))
    print(" legs exited at different times:",int(t.legs_split.sum()))
    print(" exit reasons:",t.reasons.value_counts().head(6).to_dict())
    print(" avg premiums: buy leg",round(t.prem_buy.mean()),"sell leg",round(t.prem_sell.mean()),"| avg entry spot",round(t.entry_spot.mean()))
    if name.startswith("1H"):
        m=t.groupby(t.entry_time.dt.to_period("M")).size(); print(" trades/month min/median/max",m.min(),m.median(),m.max(),"months<4:",int((m<4).sum()),"/",len(m))
        pm=t.groupby(t.exit_time.dt.to_period("M")).net.sum(); print(" months profitable",(pm>0).sum(),"/",len(pm),"worst month",round(pm.min()))
        print(" by weekday:",t.groupby(t.entry_time.dt.dayofweek).net.agg(['count','sum']).round(0).to_dict())
        t.to_csv("results/trades_monthly_synth_final.csv",index=False)
