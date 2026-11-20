"""FINAL positional setup: entry = SuperTrend+EMA+HTF EMA+VWAP on 1H; SL 50, TP 300 cap,
after +100 lock cost and trail 100 behind best. Futures vs Synthetic (Buy ATM CE + Sell ATM PE, monthly)."""
from compare_exits_synthetic import *
FINAL = dict(B, rr=6, trail_start=2, trail_pts=100)
tr = backtest(df, FINAL)
for kind in ["fut","syn"]:
    print("\n==", "FUTURES" if kind=="fut" else "SYNTHETIC FUTURES")
    for lab,(a,b) in {"Dec23-Nov24":("2023-12-01","2024-11-19"),"Nov24-Nov25":("2024-11-20","2025-11-19"),
                      "Nov25-Nov26":("2025-11-20","2026-11-21"),"LAST 2 YEARS":("2024-11-20","2026-11-21")}.items():
        t=tr[(tr.entry_time>=a)&(tr.entry_time<b)]; print(lab, evaluate(t,kind))
t2=tr[tr.entry_time>="2024-11-20"].copy()
t2["net_rs_syn"]=t2.pts*LOT-[syn_cost_rs(S) for S in t2.entry]
n=t2.net_rs_syn
print("\nwin%",round((n>0).mean()*100,1),"avg win",round(n[n>0].mean()),"avg loss",round(n[n<=0].mean()),
      "losing streak",int((n<=0).astype(int).groupby((n>0).cumsum()).sum().max()),
      "worst trade",round(n.min()),"best",round(n.max()), "exit reasons",t2.reason.value_counts().to_dict())
m=t2.set_index("exit_time").net_rs_syn.resample("ME").sum(); print("months positive",(m>0).sum(),"/",len(m))
t2.to_csv("results/trades_final_synthetic.csv",index=False)
