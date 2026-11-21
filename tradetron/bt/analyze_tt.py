import pandas as pd, numpy as np
def trades(f, sl_rs, tp_rs):
    d=pd.read_csv(f); d["t"]=pd.to_datetime(d.entry_at)
    d["sgn"]=np.where(d.txn_type=="B",-1,1)
    rows=[]
    ent=d[d.condition_type=="Entry"].sort_values("t"); ex=d[d.condition_type!="Entry"].sort_values("t")
    used=set()
    for et,g in ent.groupby("t"):
        pnl=0; xt=None; xtype=None; legs=[]
        for _,e in g.iterrows():
            cand=ex[(ex.Instrument==e.Instrument)&(ex.t>=e.t)&(~ex.id.isin(used))].head(1)
            if cand.empty: continue
            x=cand.iloc[0]; used.add(x.id)
            pnl+= -(e.amount + x.amount)
            xt=x.t if xt is None or x.t>xt else xt; xtype=x.condition_type
            legs.append((e.option_type,e.txn_type))
        side="LONG" if ("CE","B") in legs else "SHORT"
        u0=g.underlying_price.iloc[0]; u1=ex[ex.t==xt].underlying_price.iloc[0] if xt is not None else np.nan
        rows.append(dict(entry=et,exit=xt,side=side,pnl=round(pnl),exit_type=xtype,spot_move=round((u1-u0)*(1 if side=="LONG" else -1),1)))
    T=pd.DataFrame(rows)
    def cls(r):
        if r.exit_type=="Exit": return "Signal exit"
        if r.exit_type=="FinalClose": return "Window end"
        if r.pnl<=-0.8*sl_rs: return "Stop-loss"
        if r.pnl>=0.9*tp_rs: return "Target"
        if r.pnl>0: return "Trail/lock (profit)"
        return "Expiry/other exit (loss)"
    T["reason"]=T.apply(cls,axis=1); return T
M=trades("tradetron/bt/monthly_fills.csv",6500,32500); W=trades("tradetron/bt/weekly_v2_fills.csv",8000,40000)
M.to_csv("tradetron/bt/monthly_trades.csv",index=False); W.to_csv("tradetron/bt/weekly_v2_trades.csv",index=False)
def report(T,name):
    print(f"\n===== {name}: {len(T)} trades, gross P&L {T.pnl.sum():,}")
    T=T.copy(); T["d"]=T.entry.dt.date; T["wk"]=T.entry.dt.to_period("W"); T["mo"]=T.entry.dt.to_period("M"); T["yr"]=T.entry.dt.year
    sl=T.reason.eq("Stop-loss")
    per_m=T.groupby("mo").size(); allm=pd.period_range(T.mo.min(),T.mo.max(),freq="M"); per_m=per_m.reindex(allm,fill_value=0)
    print("trades per month: min",per_m.min(),"median",per_m.median(),"max",per_m.max(),"avg",round(per_m.mean(),1),"| months with 0:",(per_m==0).sum())
    print("  distribution:",per_m.value_counts().sort_index().to_dict())
    per_w=T.groupby("wk").size(); print("trades per week (weeks that traded): max",per_w.max(),"avg",round(per_w.mean(),2),"| weeks traded",len(per_w))
    per_d=T.groupby("d").size(); print("max trades in one day:",per_d.max(),"on",list(per_d[per_d==per_d.max()].index.astype(str))[:5])
    print("exit reasons:",T.reason.value_counts().to_dict())
    for lab,k in [("day","d"),("week","wk"),("month","mo"),("year","yr")]:
        s=T[sl].groupby(k).size(); p=T.groupby(k).pnl.sum()
        print(f"  per {lab}: max stop-losses {s.max() if len(s) else 0} | best {lab} +{p.max():,} ({p.idxmax()}) | worst {lab} {p.min():,} ({p.idxmin()})")
    print("  yearly P&L:",T.groupby("yr").pnl.sum().to_dict())
    n=T.pnl; st=(n<=0).astype(int); print("longest losing streak:",int(st.groupby((st!=st.shift()).cumsum()).sum().max()),"| win%",round((n>0).mean()*100,1),
          "| avg win",round(n[n>0].mean()),"avg loss",round(n[n<=0].mean()),"| best",n.max(),"worst",n.min())
    print("  same-day exits:",int((T.entry.dt.date==T.exit.dt.date).sum()),"overnight:",int((T.entry.dt.date!=T.exit.dt.date).sum()))
    print("  spot pts: losers median",T[n<=0].spot_move.median(),"winners median",T[n>0].spot_move.median())
    print("  by entry weekday:",T.groupby(T.entry.dt.day_name().str[:3]).pnl.agg(['count','sum']).to_dict('index'))
    print("  by entry hour:",T.groupby(T.entry.dt.hour).pnl.agg(['count','sum']).to_dict('index'))
    print("  by side:",T.groupby("side").pnl.agg(['count','sum']).to_dict('index'))
report(M,"NIFTY Futures Monthly"); report(W,"NIFTY Futures Weekly v2")
