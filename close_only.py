from check_15m import *
for co in [False,True]:
    tag="CLOSE-ONLY checks" if co else "tick/intrabar checks"
    t1=backtest(df,dict(P,**CYC,close_only=co))
    show(f"1H {tag} last 12m",t1,"2025-11-20","2026-11-21"); show(f"1H {tag} last 2m",t1,"2026-09-20","2026-11-21")
    x=t1[(t1.entry_time>="2025-11-20")&(t1.pts<0)]; print("    avg losing trade pts",round(x.pts.mean()),"worst",round(x.pts.min()))
    t15=backtest(d15a,dict(P,**C15,bar_min=15,close_only=co))
    show(f"15m {tag} Aug28-Nov20",t15,"2026-08-28","2026-11-21"); show(f"15m {tag} last 2m",t15,"2026-09-20","2026-11-21")
    show(f"1H {tag} Aug28-Nov20",t1,"2026-08-28","2026-11-21")
t1=backtest(df,dict(P,**CYC)); t=t1[t1.entry_time>="2026-09-20"].copy()
t["pnl_1lot_rs"]=(t.pts*LOT-[syn_cost_lots(S,1) for S in t.entry]).round(); t["side"]=t.side.map({1:"LONG",-1:"SHORT"})
t[["entry_time","exit_time","side","entry","exit","reason","pts","pnl_1lot_rs"]].round(1).to_csv("results/my_trades_last2months_1H.csv",index=False)
print(t[["entry_time","exit_time","side","entry","exit","reason","pnl_1lot_rs"]].round(0).to_string(index=False))
