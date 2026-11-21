"""MONTHLY synthetic futures (monthly ATM CE/PE), 2 lots, total-MTM SL/TP/lock (Tradetron/Algorooms style).
kill=True: an MTM exit stops the rest of that monthly cycle; kill=False: Tradetron 'Reactivate on exit' allows re-entry."""
import itertools, sys, pandas as pd, numpy as np
import weekly_combined as wc
from weekly_combined import *
from biweekly import weekly_expiries
def month_cycles(days):
    W=weekly_expiries(); M=pd.DatetimeIndex(pd.Series(W).groupby([W.year,W.month]).max().values)
    E=pd.DatetimeIndex(sorted(set([days[days<=e][-1] if e<=days[-1] else e for e in M if e>=days[0]])))
    co={d:E[E>=d][0] for d in days}; pin={}
    for a,b in zip(E[:-1],E[1:]):
        ds=days[(days>a)&(days<=b)]
        for k,d in enumerate(ds): pin[d]=(k+1,len(ds))
    return E,co,pin
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=month_cycles(days)
vix=VIX.reindex(df.index.normalize(),method="ffill").values
dh=df.High.groupby(df.index.normalize()).max().shift().reindex(df.index.normalize()).values
dl=df.Low.groupby(df.index.normalize()).min().shift().reindex(df.index.normalize()).values
c=df.Close.values
FILT={"none":None,"VIX<=18+PDH/PDL":lambda d:((c>dh)&(vix<=18),(c<dl)&(vix<=18))}
def kill_patch(kill):
    pass
if __name__=="__main__":
    rows=[]
    grid=itertools.product([6500,8000,10000],[4,5,6],["none","2R"],[2,4,99],[True,False],list(FILT),[(1,1),(1,3),(2,3)],[0,1,2])
    for sl,rr,lk,cap,kill,fn,(ks,nel),xb in grid:
        if xb>=nel and nel<=xb: pass
        lock=(2*sl,300,sl/5,sl/5) if lk=="2R" else None
        tr=run(df,60,E,co,pin,sl,sl*rr,lock,cap,(),"exp",True,filt=FILT[fn],kill=kill,exit_before=xb,no_entry_last=max(nel,xb+1) if xb>0 else nel,kstart=ks)
        if not kill and len(tr): pass
        r=dict(sl=sl,tp=sl*rr,rr=rr,lock=lk,cap=cap if cap<99 else "unl",kill=kill,filt=fn,start_day=ks,no_entry_last_days=nel,exit_days_before=xb)
        for k,(a,b) in YRS.items(): r[k]=round(tr[(tr.entry_time>=a)&(tr.entry_time<b)].net.sum()) if len(tr) else 0
        e=evw(tr[tr.entry_time>="2024-11-20"]) if len(tr) else dict(n=0,net=0,pf=0,dd=0,win=0)
        r.update({f"L2Y_{k}":v for k,v in e.items()}); r["last6m"]=round(tr[tr.entry_time>="2026-05-21"].net.sum()) if len(tr) else 0
        rows.append(r)
    R=pd.DataFrame(rows); R.to_csv("results/monthly_combined_grid.csv",index=False)
