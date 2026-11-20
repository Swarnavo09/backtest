"""Max Trade Cycle per MONTHLY expiry cycle (Algorooms CNC semantics) + CNC exit 1 trading day before expiry. 1 and 2 lots."""
import pandas as pd, numpy as np
import nifty_fut_bt as nb
from compare_exits_synthetic import *
FINAL = dict(B, rr=6, trail_start=2, trail_pts=100, exit_e21=True)
days = pd.DatetimeIndex(sorted(set(df.index.normalize())))
exp_trading = [days[days <= e][-1] if e <= days[-1] else e for e in EXP if e >= days[0]]   # holiday -> previous trading day
exp_trading = pd.DatetimeIndex(sorted(set(exp_trading)))
cycle_of, exit_day = {}, {}
for d in days:
    nxt = exp_trading[exp_trading >= d]
    e = nxt[0] if len(nxt) else days[-1] + pd.Timedelta(days=30)
    cycle_of[d] = e
for e in exp_trading:
    prev = days[days < e]
    exit_day[e] = prev[-1] if len(prev) else e
exit_day[days[-1] + pd.Timedelta(days=30)] = days[-1] + pd.Timedelta(days=60)
CYC = dict(expiries=exp_trading, cycle_of=cycle_of, exit_day=exit_day)

def syn_cost_lots(S, lots):
    P=S*0.011*LOT*lots; exch=0.0003503*4*P; sebi=0.000001*4*P
    return 80 + 0.001*2*P + exch + sebi + 0.00003*2*P + 0.18*(80+exch+sebi) + 4*1.0*LOT*lots
def ev(tr, lots=1):
    c=np.array([syn_cost_lots(S,lots) for S in tr.entry]); net=tr.pts.values*LOT*lots - c
    eq=np.cumsum(net); return dict(trades=len(tr), net_rs=round(net.sum()), pf=round(net[net>0].sum()/-net[net<=0].sum(),2),
        maxdd=round((eq-np.maximum.accumulate(eq)).min()), worst=round(net.min()), charges=round(c.sum()))
rows=[]
for cap in [2,4,6,8,10,12,15,20,999]:
    for perday in [1,99]:
        tr=backtest(df,dict(FINAL,**CYC,cycle_cap=cap,max_trades=perday))
        r={"max_trade_cycle":cap if cap<999 else "unlimited","per_day_limit":perday if perday<99 else "none"}
        for k,(a,b) in {"Y0":("2023-12-01","2024-11-19"),"Y1":("2024-11-20","2025-11-19"),"Y2":("2025-11-20","2026-11-21")}.items():
            r[k]=ev(tr[(tr.entry_time>=a)&(tr.entry_time<b)])["net_rs"]
        t2=tr[tr.entry_time>="2024-11-20"]; e=ev(t2)
        r.update(net_2y_1lot=e["net_rs"],pf=e["pf"],maxdd_1lot=e["maxdd"],trades_per_month=round(len(t2)/24,1),
                 expiry_exits=int((t2.reason=="EXPIRY").sum()))
        rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",250); print(R.to_string(index=False)); R.to_csv("results/max_trade_cycle.csv",index=False)
