import pandas as pd, numpy as np
from nifty_fut_bt import *
df=indicators(load("60m"),2)
B=dict(bar_min=60, start=570, no_trade_after=900, sq_off=10**6, max_trades=1, days=[0,1,2,3,4],
       vol=0, vwap=True, sl="pts", sl_pts=50, rr=4, sig_exit=True)
def detail(tr):
    s=stats(tr); n=tr.net
    streak=(n<=0).astype(int).groupby((n>0).cumsum()).sum().max()
    hold=(tr.exit_time-tr.entry_time).dt.total_seconds()/3600
    s.update(max_loss_rs=round(n.min()*LOT), losing_streak=int(streak), avg_hold_h=round(hold.mean(),1),
             overnight_pct=round((tr.exit_time.dt.date!=tr.entry_time.dt.date).mean()*100),
             gap_sl_beyond_60=int(((tr.reason=="SL")&(tr.pts< -60)).sum()),
             long_rs=round(tr[tr.side==1].net.sum()*LOT), short_rs=round(tr[tr.side==-1].net.sum()*LOT))
    return s
out={}
for name,v in {"RECOMMENDED SL50 1:4":{}, "SL50 1:5":dict(rr=5), "SL60 1:4":dict(sl_pts=60), "SL40 1:4":dict(sl_pts=40),
               "SL50 1:3":dict(rr=3), "SL50 1:2":dict(rr=2), "SL50 1:4 no VWAP":dict(vwap=False),
               "SL50 1:4 +Volume":dict(vol=1.2),
               "STRESS: STT 0.05%":dict(stt=0.0005), "STRESS: Mon/Tue/Thu only":dict(days=[0,1,3]),
               "OPTIMISTIC intrabar (TP first)":dict(tp_first=True)}.items():
    tr=backtest(df,dict(B,**v)); t2=tr[tr.entry_time>="2024-11-20"]; out[name]=detail(t2)
    if name.startswith("RECOMMENDED"):
        t2.to_csv("results/trades_positional_recommended.csv",index=False)
        print("Year-wise:",{y:round(g.net.sum()*LOT) for y,g in tr.groupby(tr.entry_time.dt.year)})
        q=(t2.set_index("entry_time").net*LOT).resample("QE").sum().round(-2); print("Quarterly:",q.astype(int).tolist(), "positive",(q>0).sum(),"/",len(q))
        m=(t2.set_index("entry_time").net*LOT).resample("ME").sum(); print("Months positive",(m>0).sum(),"/",len(m))
        print("3rd year (Dec23-Nov24, unseen):",detail(tr[tr.entry_time<"2024-11-20"]))
R=pd.DataFrame(out).T; pd.set_option("display.width",260); print(R.to_string()); R.to_csv("results/summary_positional_2y.csv")
# 15m cross-check, last ~60 days, true 15m/30m timeframe
d15=indicators(load("15m"),2)
for sl,rr in [(50,4),(50,3),(40,4)]:
    tr=backtest(d15,dict(B,bar_min=15,sl_pts=sl,rr=rr)); tr=tr[tr.entry_time>="2026-08-27"]
    print("15m last 3 months SL",sl,"1:"+str(rr),stats(tr))
    tr=backtest(df,dict(B,sl_pts=sl,rr=rr)); tr=tr[tr.entry_time>="2026-08-27"]
    print("60m same 3 months  SL",sl,"1:"+str(rr),stats(tr))
