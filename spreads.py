"""Credit-spread prototypes (high win-rate, defined risk). BS pricing from Nifty + India VIX (no skew -> indicative only).
direction from the trend signal: up -> bull put spread, down -> bear call spread; 'neutral' -> iron condor."""
import itertools, math, sys, pandas as pd, numpy as np
from nifty_fut_bt import *
from synthetic_legs import bs, VIX, leg_cost
from biweekly import weekly_expiries, YRS
LOTS=2
def cycles(days, kind):
    W=weekly_expiries()
    E=W if kind=="weekly" else pd.DatetimeIndex(pd.Series(W).groupby([W.year,W.month]).max().values)
    E=pd.DatetimeIndex(sorted(set([days[days<=e][-1] if e<=days[-1] else e for e in E if e>=days[0]])))
    return E
def run_spread(df, kind, mode="trend", short_off=0, width=200, tp_frac=0.5, sl_mult=1.0, min_dte=2, max_dte=40, entry_t=(615,900), exit_dte=0, intraday=False, vix_max=99, iv_mult=1.0):
    days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E=cycles(days,kind)
    up=((df.Close>df.st)&(df.e9>df.e21)&(df.h9>df.h21)).values; dn=((df.Close<df.st)&(df.e9<df.e21)&(df.h9<df.h21)).values
    t=df.index; o,h,l,c=df.Open.values,df.High.values,df.Low.values,df.Close.values; tm=(t.hour*60+t.minute).values; q=LOT*LOTS
    trades=[]; pos=None; last_day=None
    for i in range(30,len(df)):
        d=t[i].normalize(); ct=tm[i]+60; iv=float(VIX.asof(d))/100*iv_mult
        exp=E[E>=d]; 
        if not len(exp): break
        if pos:
            T=max((pos["exp"]+pd.Timedelta(hours=15.5)-(t[i]+pd.Timedelta(minutes=60))).total_seconds(),60)/86400/365
            def val(s): return sum(sg*bs(s,K,T,iv,cp) for sg,K,cp in pos["legs"])   # value of the position we are SHORT (credit structure)
            worst=max(val(h[i]),val(l[i])); best=min(val(h[i]),val(l[i])); vo=val(o[i]); vc=val(c[i])
            ex=None; cr=pos["credit"]
            if vo-cr>=sl_mult*cr: ex=(vo,"SL")
            elif vo<=cr*(1-tp_frac): ex=(vo,"TP")
            elif worst-cr>=sl_mult*cr: ex=(cr*(1+sl_mult),"SL")
            elif best<=cr*(1-tp_frac): ex=(cr*(1-tp_frac),"TP")
            dte=int(((days>d)&(days<=pos["exp"])).sum())
            if not ex and intraday and ct>=915: ex=(vc,"EOD")
            if not ex and dte<=exit_dte and ct>=(900 if dte==0 else 915): ex=(vc,"TIME")
            if ex:
                pnl=(cr-ex[0])*q; cost=sum(leg_cost(max(p,0.5),max(p,0.5),True,LOTS) for p in pos["prem"])
                trades.append(dict(entry=pos["t"],exit=t[i],kind=pos["k"],credit=cr,pnl=pnl-cost,reason=ex[1]))
                pos=None; last_day=d
            continue
        if d==last_day or ct<entry_t[0] or ct>entry_t[1]: continue
        if iv*100/iv_mult>vix_max: continue
        e0=exp[0]; dte=int(((days>d)&(days<=e0)).sum())
        if dte<min_dte: 
            e0=exp[1] if len(exp)>1 else None
            if e0 is None: continue
            dte=int(((days>d)&(days<=e0)).sum())
        if dte>max_dte: continue
        T=max((e0+pd.Timedelta(hours=15.5)-(t[i]+pd.Timedelta(minutes=60))).total_seconds(),60)/86400/365
        atm=round(c[i]/50)*50; legs=[]
        if mode in ("trend","both") and up[i]: legs=[(1,atm-short_off,False),(-1,atm-short_off-width,False)]; k="bull put"
        elif mode in ("trend","both") and dn[i]: legs=[(1,atm+short_off,True),(-1,atm+short_off+width,True)]; k="bear call"
        elif mode in ("neutral",) or (mode=="both"): legs=[(1,atm-short_off,False),(-1,atm-short_off-width,False),(1,atm+short_off,True),(-1,atm+short_off+width,True)]; k="condor"
        if not legs: continue
        prem=[bs(c[i],K,T,iv,cp) for _,K,cp in legs]; cr=sum(sg*p for (sg,_,_),p in zip(legs,prem))
        if cr<=5: continue
        pos=dict(t=t[i],exp=e0,legs=legs,credit=cr,prem=prem,k=k)
    return pd.DataFrame(trades)
def stats(tr):
    if len(tr)==0: return dict(n=0)
    n=tr.pnl.values; eq=np.cumsum(n); pos=n[n>0]
    top5=np.sort(pos)[::-1][:5].sum()/n.sum() if n.sum()>0 else np.nan
    m=tr.set_index("exit").pnl.resample("ME").sum()
    return dict(n=len(n),net=round(n.sum()),win=round((n>0).mean()*100),pf=round(pos.sum()/-n[n<=0].sum(),2) if ((n<=0).any() and n[n<=0].sum()<0) else 9.9,
                dd=round((eq-np.maximum.accumulate(eq)).min()),top1_share=round(pos.max()/n.sum()*100) if (n.sum()>0 and len(pos)) else None,
                top5_share=round(top5*100) if n.sum()>0 else None,months_pos=f"{(m>0).sum()}/{len(m)}",worst_mo=round(m.min()),avg_win=round(pos.mean()) if len(pos) else 0,avg_loss=round(n[n<=0].mean()) if (n<=0).any() else 0)
if __name__=="__main__":
    df=indicators(load("60m"),2); rows=[]
    for kind in ["weekly","monthly"]:
        for mode,off,width,tp,slm,intra,ed in itertools.product(["trend","neutral"],[0,100,200],[200,300],[0.5,0.7],[1.0,1.5],[False,True],[0,1]):
            if intra and ed==1: continue
            mn,mx=(1,6) if kind=="weekly" else (5,30)
            tr=run_spread(df,kind,mode,off,width,tp,slm,mn,mx,(615,900),ed,intra)
            t2=tr[tr.entry>="2024-11-20"] if len(tr) else tr
            r=dict(kind=kind,mode=mode,short_off=off,width=width,tp=tp,sl=slm,intraday=intra,exit_dte=ed)
            for y,(a,b) in YRS.items(): r[y]=round(tr[(tr.entry>=a)&(tr.entry<b)].pnl.sum()) if len(tr) else 0
            r.update(stats(t2)); rows.append(r)
    R=pd.DataFrame(rows); R.to_csv("results/spreads_grid.csv",index=False)
