"""Fix: per-trade SL/TP on a NIFTY FUTURES leg (Stocks & Futures - Indicator Based), no overall-M2M cycle kill."""
from cycle_cap import *
def fut_cost_lots(S,lots):
    T=S*LOT*lots; exch=0.0000173*2*T; sebi=0.000001*2*T
    return 40 + 0.0002*T + exch + sebi + 0.00002*T + 0.18*(40+exch+sebi) + 2*1.0*LOT*lots
def evf(tr,lots):
    c=np.array([fut_cost_lots(S,lots) for S in tr.entry]); net=tr.pts.values*LOT*lots-c; eq=np.cumsum(net)
    return dict(trades=len(tr),net=round(net.sum()),pf=round(net[net>0].sum()/-net[net<=0].sum(),2),dd=round((eq-np.maximum.accumulate(eq)).min()))
V={"SL50 TP300, lock-and-trail (+100 then 100 behind)":dict(rr=6,trail_start=2,trail_pts=100),
   "SL50 TP300, no trail":dict(rr=6),
   "SL50 TP200, no trail":dict(rr=4),
   "SL50 TP300, trail SL 50 behind from start (X10/Y10)":dict(rr=6,trail_start=0.0001,trail_pts=50),
   "SL50 TP300, trail starts at +50, 100 behind":dict(rr=6,trail_start=1,trail_pts=100),
   "SL50 TP300, breakeven at +100 only":dict(rr=6,be_at=2)}
rows=[]
for name,v in V.items():
    p=dict(FINAL,**CYC,cycle_cap=10,max_trades=99); p.update(trail_start=0,trail_pts=0,be_at=0); p.update(v)
    tr=backtest(df,p)
    r={"exit":name}
    for k,(a,b) in {"Y0":("2023-12-01","2024-11-19"),"Y1":("2024-11-20","2025-11-19"),"Y2":("2025-11-20","2026-11-21")}.items():
        r[k+"_1lot"]=evf(tr[(tr.entry_time>=a)&(tr.entry_time<b)],1)["net"]
    t2=tr[tr.entry_time>="2024-11-20"]; e1=evf(t2,1); e2=evf(t2,2)
    r.update(trades_2y=e1["trades"],net_2y_1lot=e1["net"],net_2y_2lots=e2["net"],pf=e2["pf"],dd_2lots=e2["dd"]); rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",250); print(R.to_string(index=False)); R.to_csv("results/futures_leg_level.csv",index=False)
