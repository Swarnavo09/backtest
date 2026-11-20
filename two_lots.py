from cycle_cap import *
tr=backtest(df,dict(FINAL,**CYC,cycle_cap=10,max_trades=99))
for lots in [1,2]:
    print(f"\n== {lots} LOT(S), Max Trade Cycle 10")
    for k,(a,b) in {"Dec23-Nov24":("2023-12-01","2024-11-19"),"Nov24-Nov25":("2024-11-20","2025-11-19"),"Nov25-Nov26":("2025-11-20","2026-11-21"),"LAST 2 YEARS":("2024-11-20","2026-11-21")}.items():
        print(k, ev(tr[(tr.entry_time>=a)&(tr.entry_time<b)],lots))
    t2=tr[tr.entry_time>="2024-11-20"]
    net=t2.pts.values*LOT*lots-np.array([syn_cost_lots(S,lots) for S in t2.entry])
    m=pd.Series(net,index=t2.exit_time.values).resample("ME").sum()
    print("months +ve",(m>0).sum(),"/",len(m),"avg month",round(m.mean()),"worst month",round(m.min()),"best month",round(m.max()),
          "avg win",round(net[net>0].mean()),"avg loss",round(net[net<=0].mean()),"win%",round((net>0).mean()*100),
          "losing streak",int(pd.Series(net<=0).astype(int).groupby(pd.Series(net>0).cumsum()).sum().max()))
