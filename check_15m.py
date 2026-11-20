from cycle_cap import *
def cyc_for(dfx):
    ds=pd.DatetimeIndex(sorted(set(dfx.index.normalize())))
    ex=pd.DatetimeIndex(sorted(set([ds[ds<=e][-1] if e<=ds[-1] else e for e in EXP if e>=ds[0]])))
    co={d:(ex[ex>=d][0]) for d in ds}; ed={e:(ds[ds<e][-1] if len(ds[ds<e]) else e) for e in ex}
    return dict(expiries=ex,cycle_of=co,exit_day=ed)
P=dict(FINAL,cycle_cap=10,max_trades=99)
tr60=backtest(df,dict(P,**CYC))
def show(lab,tr,a,b):
    t=tr[(tr.entry_time>=a)&(tr.entry_time<b)]; print(f"{lab:45s}",ev(t) if len(t) else "no trades")
print("--- my 1H engine")
show("1H last 12 months (Nov25-Nov26)",tr60,"2025-11-20","2026-11-21")
show("1H last 2 months (Sep20-Nov20)",tr60,"2026-09-20","2026-11-21")
show("1H 15m-window (Aug28-Nov20)",tr60,"2026-08-28","2026-11-21")
t=tr60[(tr60.entry_time>="2025-11-20")]; big=t[t.pts>350]; print("last-12m trades >350 pts (gap windfalls):",len(big),"worth Rs",round(big.pts.sum()*LOT), big[["entry_time","side","pts"]].to_string())
d15a=indicators(load("15m"),2); d15b=indicators(load("15m"),8)
C15=cyc_for(d15a)
for lab,d,ln in [("15m same lengths (EMA9/21,18/42,ST10)",d15a,1),("15m with 1H-equivalent lengths (x4)",None,4)]:
    if ln==4:
        import nifty_fut_bt as nb
        d=load("15m").copy()
        x=d.copy(); x["st"],x["st_dir"]=supertrend(x,40,3); x["e9"],x["e21"]=ema(x.Close,36),ema(x.Close,84); x["h9"],x["h21"]=ema(x.Close,72),ema(x.Close,168)
        x["atr"]=atr(x,56); day=x.index.normalize(); tp=(x.High+x.Low+x.Close)/3
        x["vwap"]=(tp*x.Volume).groupby(day).cumsum()/x.Volume.groupby(day).cumsum(); x["rvol"]=1.0; x["d_up"]=True; d=x
    tr=backtest(d,dict(P,**C15,bar_min=15))
    show(lab+" Aug28-Nov20",tr,"2026-08-28","2026-11-21"); show(lab+" last 2 months",tr,"2026-09-20","2026-11-21")
    for sl,rr,tr_ in [(30,6,60),(40,6,80)]:
        tr=backtest(d,dict(P,**C15,bar_min=15,sl_pts=sl,trail_pts=tr_))
        show(f"   {lab[:20]} SL{sl} trail{tr_} Aug28-Nov20",tr,"2026-08-28","2026-11-21")
# sensitivity to VWAP (proxy-volume risk) and to entering at NEXT bar open
show("1H last 12m WITHOUT VWAP",backtest(df,dict(P,**CYC,vwap=False)),"2025-11-20","2026-11-21")
