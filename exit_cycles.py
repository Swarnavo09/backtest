"""Exit conditions (all implementable in Algorooms 'Exit Conditions') x trade cycles, on top of the final setup."""
import pandas as pd
from compare_exits_synthetic import *
FINAL = dict(B, rr=6, trail_start=2, trail_pts=100)
exits = {"None (SL/trail/TP only)":{}, "Close X below EMA21":dict(exit_e21=True), "Close X below SuperTrend":dict(exit_st=True),
         "EMA9 X below EMA21":dict(exit_ema=True), "Close X below VWAP":dict(exit_vwap=True),
         "EMA18 X below EMA42":dict(sig_exit=True), "Time stop 2 days":dict(time_stop=14), "Time stop 3 days":dict(time_stop=21)}
rows=[]
for (en,ev),mt in itertools.product(exits.items(),[1,2,3]):
    tr=backtest(df,dict(FINAL,**ev,max_trades=mt))
    r={"exit":en,"cycles/day":mt}
    for k,(a,b) in {"Y0":("2023-12-01","2024-11-19"),"Y1":("2024-11-20","2025-11-19"),"Y2":("2025-11-20","2026-11-21")}.items():
        r[k]=evaluate(tr[(tr.entry_time>=a)&(tr.entry_time<b)],"syn")["net_rs"]
    t2=tr[tr.entry_time>="2024-11-20"]; e=evaluate(t2,"syn")
    hold=(t2.exit_time-t2.entry_time).dt.total_seconds()/86400
    r.update(net_2y=e["net_rs"],pf=e["pf"],maxdd=e["maxdd"],trades_mo=round(len(t2)/24,1),
             win=round(((t2.pts*LOT-419)>0).mean()*100),avg_hold_d=round(hold.mean(),2),max_hold_d=round(hold.max(),1))
    rows.append(r)
R=pd.DataFrame(rows); pd.set_option("display.width",250); print(R.to_string(index=False)); R.to_csv("results/exit_conditions_cycles.csv",index=False)
