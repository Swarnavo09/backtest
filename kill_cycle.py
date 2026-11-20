from cycle_cap import *
for kc in [True,False]:
    tr=backtest(df,dict(FINAL,**CYC,cycle_cap=10,max_trades=99,kill_cycle=kc))
    t=tr[(tr.entry_time>="2024-12-16")&(tr.entry_time<"2026-10-01")]
    e=ev(t,2); print("kill_cycle" if kc else "normal   ", "trades",e["trades"],"per month",round(len(t)/21.5,1),"gross 2 lots",round(t.pts.sum()*LOT*2),"net",e["net_rs"],"pf",e["pf"],"dd",e["maxdd"])
