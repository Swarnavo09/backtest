from synthetic_legs import *
for iv_,bar,per in [("60m",60,dict(YRS,L2Y=("2024-11-20","2026-11-21"))),("15m",15,{"15m_window":("2026-08-28","2026-11-21")})]:
    df=indicators(load(iv_),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); cyc=make_cycles(days,"biweekly")
    for cap in [5,8,10,12,15,99]:
        tr=simulate(df,bar,cyc,20,0,(40,20),cap)
        out={k:evn(tr[(tr.entry_time>=a)&(tr.entry_time<b)]) for k,(a,b) in per.items()}
        print(iv_,"cap",cap,{k:(v["n"],v["net"],v["pf"],v["dd"]) for k,v in out.items()})
        if iv_=="60m" and cap==10:
            t=tr[tr.entry_time>="2024-11-20"]; n=t.net
            print("   win%",round((n>0).mean()*100),"avg win",round(n[n>0].mean()),"avg loss",round(n[n<=0].mean()),"worst",round(n.min()),
                  "trades/cycle",round(t.groupby(t.entry_time.dt.to_period("W")).size().sum()/52,1),
                  "months+",( n.groupby(t.exit_time.dt.to_period("M")).sum()>0).sum(),"/",t.exit_time.dt.to_period("M").nunique())
            t.to_csv("results/trades_biweekly_synthetic_final.csv",index=False)
