"""Bi-weekly synthetic futures with PER-LEG SL/TP/trail (how an Algorooms options strategy applies leg settings).
Option premiums are estimated with Black-Scholes from the Nifty path, IV = India VIX (daily), strike = ATM (50 step)."""
import itertools, math, pandas as pd, numpy as np
from nifty_fut_bt import *
from biweekly import make_cycles, YRS
class norm:
    @staticmethod
    def cdf(x): return 0.5*(1+math.erf(x/math.sqrt(2)))

VIX = pd.read_pickle("data/vix_1d.pkl")["Close"].squeeze(); VIX.index = VIX.index.normalize()

def bs(S, K, T, iv, call):
    T = max(T, 1/365/24); d1 = (math.log(S/K) + 0.5*iv*iv*T)/(iv*math.sqrt(T)); d2 = d1 - iv*math.sqrt(T)
    return S*norm.cdf(d1) - K*norm.cdf(d2) if call else K*norm.cdf(-d2) - S*norm.cdf(-d1)

def signals(df):
    L = (df.Close>df.st)&(df.Close>df.e21)&(df.e9>df.e21)&(df.h9>df.h21)&(df.Close>df.vwap)
    S = (df.Close<df.st)&(df.Close<df.e21)&(df.e9<df.e21)&(df.h9<df.h21)&(df.Close<df.vwap)
    return L.values, S.values

def leg_cost(prem_in, prem_out, sell_first, lots=1):
    q=LOT*lots; turn=(prem_in+prem_out)*q; sell_val=(prem_in if sell_first else prem_out)*q
    exch=0.0003503*turn; return 40 + 0.001*sell_val + exch + 0.000001*turn + 0.00003*(turn-sell_val) + 0.18*(40+exch) + 2*1.0*q

def simulate(df, bar_min, cyc, sl, tp, trail=None, cap=99, exit_e21=True, overall=None, kill=False, lots=1):
    """trail=(X,Y): every X pts favourable move in a leg's premium, move that leg's SL by Y.
       overall=(loss_rs, profit_rs) combined M2M exit; kill=True -> that exit ends the cycle."""
    L, Sg = signals(df); t=df.index; o,h,l,c = df.Open.values, df.High.values, df.Low.values, df.Close.values
    e21=df.e21.values; tm=t.hour*60+t.minute; days=t.normalize()
    trades=[]; pos=None; cnt={}
    for i in range(30,len(df)):
        d=days[i]; cy=cyc["cycle_of"][d]; close_t=tm[i]+bar_min
        iv=float(VIX.asof(d))/100
        if pos:
            T=lambda s: max((pos["exp"]+pd.Timedelta(hours=15.5) - (t[i]+pd.Timedelta(minutes=bar_min))).total_seconds(),0)/86400/365
            Tn=T(None); done_all=False
            for leg in pos["legs"]:
                if leg["out"] is not None: continue
                # worst & best spot in the bar for this leg
                def val(s): return bs(s, pos["K"], Tn, iv, leg["call"])
                vals=[val(o[i]), val(h[i]), val(l[i]), val(c[i])]
                sgn = 1 if leg["buy"] else -1                     # P&L sign per premium point
                pnl_pts=[sgn*(v-leg["in"]) for v in vals]
                worst=min(pnl_pts[1:3]); best=max(pnl_pts[1:3])
                if sgn*(vals[0]-leg["in"]) <= -leg["sl"]: leg["out"]=(vals[0],"SL")          # gap through SL
                elif worst <= -leg["sl"]: leg["out"]=(leg["in"]-sgn*leg["sl"],"SL")
                elif tp and best >= tp: leg["out"]=(leg["in"]+sgn*tp,"TP")
                elif trail:
                    leg["best"]=max(leg["best"],best); steps=int(leg["best"]//trail[0])
                    leg["sl"]=min(leg["sl0"], leg["sl0"]-steps*trail[1]) if steps else leg["sl0"]
            # exit condition / cycle end / overall M2M on combined position (at bar close)
            m2m=sum(((lg["out"][0] if lg["out"] else bs(c[i],pos["K"],Tn,iv,lg["call"]))-lg["in"])*(1 if lg["buy"] else -1) for lg in pos["legs"])*LOT*lots
            reason=None
            if exit_e21 and ((pos["side"]==1 and c[i]<e21[i]) or (pos["side"]==-1 and c[i]>e21[i])): reason="COND"
            if d>=cyc["exit_day"][pos["cyc"]] and close_t>=910: reason="EXPIRY"
            if overall and (m2m<=-overall[0] or m2m>=overall[1]): reason="M2M"
            for lg in pos["legs"]:
                if lg["out"] is None and reason: lg["out"]=(bs(c[i],pos["K"],Tn,iv,lg["call"]),reason)
            if all(lg["out"] for lg in pos["legs"]):
                gross=sum((lg["out"][0]-lg["in"])*(1 if lg["buy"] else -1) for lg in pos["legs"])*LOT*lots
                cost=sum(leg_cost(lg["in"],lg["out"][0],not lg["buy"],lots) for lg in pos["legs"])
                trades.append(dict(entry_time=pos["t"],exit_time=t[i],side=pos["side"],K=pos["K"],gross=gross,cost=cost,net=gross-cost,
                                   reasons="/".join(lg["out"][1] for lg in pos["legs"])))
                if kill and reason=="M2M": cnt[pos["cyc"]]=10**9
                pos=None
            continue
        if d>=cyc["exit_day"][cy] or cnt.get(cy,0)>=cap or close_t<570 or close_t>900: continue
        side=1 if L[i] else (-1 if Sg[i] else 0)
        if not side: continue
        K=round(c[i]/50)*50; exp=cy; Tn=max((exp+pd.Timedelta(hours=15.5)-(t[i]+pd.Timedelta(minutes=bar_min))).total_seconds(),0)/86400/365
        ce=bs(c[i],K,Tn,iv,True); pe=bs(c[i],K,Tn,iv,False)
        legs=[dict(call=(side==1),buy=True,in_=0),dict(call=(side!=1),buy=False)]
        legs[0]["in"]=ce if side==1 else pe; legs[1]["in"]=pe if side==1 else ce
        for lg in legs:
            lg.update(sl=sl,sl0=sl,out=None,best=0.0)
        pos=dict(side=side,K=K,exp=exp,cyc=cy,t=t[i],legs=legs); cnt[cy]=cnt.get(cy,0)+1
    return pd.DataFrame(trades)

def evn(tr):
    if len(tr)==0: return dict(n=0,net=0,pf=0,dd=0)
    n=tr.net.values; eq=np.cumsum(n); lo=-n[n<=0].sum()
    return dict(n=len(n),net=round(n.sum()),pf=round(n[n>0].sum()/lo,2) if lo else 9.99,dd=round((eq-np.maximum.accumulate(eq)).min()))
