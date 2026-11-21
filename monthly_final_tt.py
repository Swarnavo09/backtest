import pandas as pd, numpy as np
from monthly_combined import *
def streak(n):
    s=(n<=0).astype(int); return int(s.groupby((s!=s.shift()).cumsum()).sum().max()) if len(n) else 0
V={"ACTIVE (no filter)":dict(filt=None),"CAREFUL (VIX<=18 + PDH/PDL breakout)":dict(filt=FILT["VIX<=18+PDH/PDL"])}
base=dict(sl_rs=6500,tp_rs=32500,lock=(13000,300,1300,1300),cap=99,entry_days=(),exit_mode="exp",ema_exit=True,kill=False,exit_before=1,no_entry_last=3,kstart=2)
rows=[]
for vn,v in V.items():
    for hedge in [0,300,500]:
        for lk in ["2R","none"]:
            p=dict(base,**v,hedge=hedge); 
            if lk=="none": p["lock"]=None
            tr=run(df,60,E,co,pin,**p)
            r={"variant":vn,"hedge_pts":hedge,"lock":lk}
            for k,(a,b) in YRS.items(): r[k]=round(tr[(tr.entry_time>=a)&(tr.entry_time<b)].net.sum())
            for lab,st in [("6m","2026-05-21"),("3m","2026-08-21"),("1m","2026-10-21")]: r[lab]=round(tr[tr.entry_time>=st].net.sum())
            t=tr[tr.entry_time>="2024-11-20"]; e=evw(t); n=t.net.reset_index(drop=True)
            m=t.set_index("exit_time").net.resample("ME").sum()
            r.update(trades_2y=e["n"],per_month=round(e["n"]/24,1),net_2y=e["net"],pf=e["pf"],maxdd=e["dd"],win=e["win"],
                     avg_win=round(t[t.net>0].net.mean()),avg_loss=round(t[t.net<=0].net.mean()),worst=round(t.net.min()),
                     loss_streak=streak(n),months_pos=f"{(m>0).sum()}/{len(m)}",same_day=int((t.entry_time.dt.date==t.exit_time.dt.date).sum()))
            rows.append(r)
            if hedge==0 and lk=="2R": tr.to_csv(f"results/trades_monthly_tt_{'active' if 'ACTIVE' in vn else 'careful'}.csv",index=False)
R=pd.DataFrame(rows); pd.set_option("display.width",280); pd.set_option("display.max_columns",30); print(R.to_string(index=False)); R.to_csv("results/monthly_tt_final.csv",index=False)
for f in ["active","careful"]:
    t=pd.read_csv(f"results/trades_monthly_tt_{f}.csv",parse_dates=["entry_time","exit_time"]); t=t[t.entry_time>="2024-11-20"]
    print(f, "exit reasons",t.reason.value_counts().to_dict(),"| spot pts losers median",round(t[t.net<=0].spot_move.median()),"winners median",round(t[t.net>0].spot_move.median()),
          "| by weekday",t.groupby(t.entry_time.dt.dayofweek).net.sum().round(-3).to_dict())
