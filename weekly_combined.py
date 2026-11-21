"""WEEKLY synthetic futures, 2 lots, NO leg SL: one combined (total M2M) stop, target and optional lock-and-trail,
exactly like Algorooms Risk Management. An overall M2M exit stops the rest of that weekly cycle (Algorooms behaviour).
Option prices: Black-Scholes from Nifty path, IV = India VIX, ATM strike, current weekly expiry."""
import itertools, sys, math, pandas as pd, numpy as np
from nifty_fut_bt import *
from synthetic_legs import bs, signals, leg_cost, VIX
from biweekly import weekly_expiries, YRS

def week_cycles(days):
    W=weekly_expiries(); E=pd.DatetimeIndex(sorted(set([days[days<=e][-1] if e<=days[-1] else e for e in W if e>=days[0]])))
    co={}; pos_in={}
    for d in days:
        e=E[E>=d][0]; co[d]=e
    # trading-day index inside the cycle: 1 = first day after previous expiry
    for e_prev,e in zip(E[:-1],E[1:]):
        ds=days[(days>e_prev)&(days<=e)]
        for k,d in enumerate(ds): pos_in[d]=(k+1,len(ds))
    return E,co,pos_in

def run(df, bar, E, co, pos_in, sl_rs, tp_rs, lock=None, cap=1, entry_days=(1,2,3,4), exit_mode="pre", ema_exit=True,
        lots=2, skip_wd=(), filt=None, exit_before=None, no_entry_last=None, kstart=1, kill=True, hedge=0, no_same_day=False, max_sl_cycle=None, no_entry_after=None):
    """lock=(trigger_rs, lock_rs, step_rs, raise_rs) on combined M2M. exit_mode: 'pre' = 15:10 day before expiry, 'exp' = 15:00 expiry day."""
    L,S=signals(df)
    if filt is not None:
        fl,fs=filt(df); L=L&fl; S=S&fs
    t=df.index; o,h,l,c=df.Open.values,df.High.values,df.Low.values,df.Close.values; e21=df.e21.values
    tm=t.hour*60+t.minute; days=t.normalize(); q=LOT*lots
    trades=[]; pos=None; cnt={}; last_exit_day=None; slc={}
    for i in range(30,len(df)):
        d=days[i]
        if d not in pos_in: continue
        cy=co[d]; k,n=pos_in[d]; close_t=tm[i]+bar; iv=float(VIX.asof(d))/100
        Trem=lambda: max((cy+pd.Timedelta(hours=15.5)-(t[i]+pd.Timedelta(minutes=bar))).total_seconds(),60)/86400/365
        if pos:
            T=max((pos["exp"]+pd.Timedelta(hours=15.5)-(t[i]+pd.Timedelta(minutes=bar))).total_seconds(),60)/86400/365
            V=lambda s: pos["side"]*(bs(s,pos["K"],T,iv,True)-bs(s,pos["K"],T,iv,False)) + (bs(s,pos["KH"],T,iv,pos["side"]==-1) if pos["KH"] else 0.0)
            m_open=(V(o[i])-pos["V0"])*q; adv=l[i] if pos["side"]==1 else h[i]; fav=h[i] if pos["side"]==1 else l[i]
            m_worst=(V(adv)-pos["V0"])*q; m_best=(V(fav)-pos["V0"])*q; m_close=(V(c[i])-pos["V0"])*q
            stop=pos["stop"]; ex=None
            if m_open<=stop: ex=(m_open,"M2M_SL" if stop<0 else "M2M_LOCK",o[i])
            elif tp_rs and m_open>=tp_rs: ex=(m_open,"M2M_TP",o[i])
            elif m_worst<=stop: ex=(stop,"M2M_SL" if stop<0 else "M2M_LOCK",adv)        # stop first if both in bar
            elif tp_rs and m_best>=tp_rs: ex=(tp_rs,"M2M_TP",fav)
            if not ex and lock:
                pos["best"]=max(pos["best"],m_best)
                if pos["best"]>=lock[0]:
                    pos["stop"]=max(pos["stop"], lock[1]+math.floor((pos["best"]-lock[0])/lock[2])*lock[3])
            if not ex and ema_exit and ((pos["side"]==1 and c[i]<e21[i]) or (pos["side"]==-1 and c[i]>e21[i])): ex=(m_close,"COND",c[i])
            if not ex and exit_mode=="intra" and close_t>=910: ex=(m_close,"EOD",c[i])
            if not ex:
                if exit_before is not None:
                    pk,pn=pos["kn"] if False else (k,n)
                    last_day = (k==n-exit_before); tcut = 910 if exit_before>0 else 900
                else:
                    last_day = (k==n-1) if exit_mode=="pre" else (k==n); tcut = 910 if exit_mode=="pre" else 900
                if last_day and close_t>=tcut: ex=(m_close,"EXPIRY_EXIT",c[i])
            if ex:
                ce_in,pe_in=pos["ce"],pos["pe"]; cost=leg_cost(ce_in,ce_in,pos["side"]==-1,lots)+leg_cost(pe_in,pe_in,pos["side"]==1,lots)+(leg_cost(pos["h0"],pos["h0"],False,lots) if pos["KH"] else 0)
                trades.append(dict(entry_time=pos["t"],exit_time=t[i],side=pos["side"],gross=ex[0],cost=cost,net=ex[0]-cost,reason=ex[1],
                                   entry_spot=pos["spot"],spot_move=(ex[2]-pos["spot"])*pos["side"],entry_wd=pos["t"].dayofweek,cycle_day=pos["k"],
                                   cycle=str(pos["exp"].date()),prem=(ce_in+pe_in)/2))
                if kill and ex[1].startswith("M2M"): cnt[pos["exp"]]=10**9
                last_exit_day=d
                if ex[1]=="M2M_SL": slc[pos["exp"]]=slc.get(pos["exp"],0)+1
                pos=None
            continue
        if max_sl_cycle is not None and slc.get(cy,0)>=max_sl_cycle: continue
        if no_entry_after is not None and close_t>no_entry_after: continue
        if no_same_day and last_exit_day is not None and d==last_exit_day: continue
        if no_entry_last is not None:
            if k < kstart or k > n-no_entry_last: continue
        elif k not in entry_days: continue
        if cnt.get(cy,0)>=cap or close_t<570 or close_t>900 or t[i].dayofweek in skip_wd: continue
        if no_entry_last is None and exit_mode=="pre" and k>=n-1: continue
        side=1 if L[i] else (-1 if S[i] else 0)
        if not side: continue
        K=round(c[i]/50)*50; T=Trem(); ce=bs(c[i],K,T,iv,True); pe=bs(c[i],K,T,iv,False)
        KH=(K-side*hedge) if hedge else 0; h0=bs(c[i],KH,T,iv,side==-1) if hedge else 0.0
        pos=dict(side=side,K=K,exp=cy,t=t[i],spot=c[i],V0=side*(ce-pe)+h0,ce=ce,pe=pe,stop=-sl_rs,best=0.0,k=k,KH=KH,h0=h0)
        cnt[cy]=cnt.get(cy,0)+1
    return pd.DataFrame(trades)

def evw(tr):
    if len(tr)==0: return dict(n=0,net=0,pf=0,dd=0,win=0)
    n=tr.net.values; eq=np.cumsum(n); lo=-n[n<=0].sum()
    return dict(n=len(n),net=round(n.sum()),pf=round(n[n>0].sum()/lo,2) if lo else 9.99,dd=round((eq-np.maximum.accumulate(eq)).min()),win=round((n>0).mean()*100))

if __name__=="__main__":
    iv_=sys.argv[1] if len(sys.argv)>1 else "60m"; bar=60 if iv_=="60m" else 15
    df=indicators(load(iv_),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize())))
    E,co,pin=week_cycles(days)
    P=dict(YRS,L2Y=("2024-11-20","2026-11-21")) if bar==60 else {"W":("2026-08-28","2026-11-21")}
    rows=[]
    SLs=[3000,4000,5000,6500,8000]
    for sl,rr,lk,cap,ed,em,ema in itertools.product(SLs,[4,5,6,0],["none","2R->cost,trail 2R","1R->cost,trail 1R"],[1,2,3],
                                                    [(1,2,3,4),(1,),(1,2),(2,3,4)],["pre"],[True,False]):
        lock=None
        if lk=="2R->cost,trail 2R": lock=(2*sl,300,sl/5,sl/5)
        if lk=="1R->cost,trail 1R": lock=(1*sl,300,sl/5,sl/5)
        tr=run(df,bar,E,co,pin,sl,sl*rr,lock,cap,ed,em,ema)
        r=dict(sl=sl,tp=sl*rr if rr else "none",rr=rr or "open",lock=lk,cap=cap,entry_days=str(ed),ema_exit=ema)
        for kk,(a,b) in P.items():
            e=evw(tr[(tr.entry_time>=a)&(tr.entry_time<b)] if len(tr) else tr); r.update({f"{kk}_{f}":v for f,v in e.items()})
        rows.append(r)
    R=pd.DataFrame(rows); R.to_csv(f"results/weekly_combined_{iv_}.csv",index=False)
    pd.set_option("display.width",270); pd.set_option("display.max_columns",40)
    if bar==60:
        R["min_year"]=R[["Y0_net","Y1_net","Y2_net"]].min(axis=1); R["score"]=R.L2Y_net/(-R.L2Y_dd).clip(lower=1)
        print("configs:",len(R),"all-years-profitable:",(R.min_year>0).sum())
        print(R[R.min_year>0].sort_values("score",ascending=False).head(20).to_string(index=False))
    else:
        print(R.sort_values("W_net",ascending=False).head(20).to_string(index=False))
