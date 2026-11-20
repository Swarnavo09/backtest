"""Weekly / BI-WEEKLY / monthly option cycles (Algorooms CNC), with and without the
'overall M2M exit stops the cycle' behaviour, SL/TP/trail grid and Max Trade Cycle."""
import itertools, sys, pandas as pd, numpy as np
from nifty_fut_bt import *

def weekly_expiries(start="2023-11-01", end="2027-01-31"):
    out=[]
    for d in pd.date_range(start,end,freq="D"):
        wd = 1 if d >= pd.Timestamp("2025-09-01") else 3     # Tue from Sep-2025, Thu before
        if d.dayofweek==wd: out.append(d)
    return pd.DatetimeIndex(out)

def make_cycles(days, kind):
    W = weekly_expiries()
    if kind=="weekly": E=W
    elif kind=="biweekly": E=W[::2]
    else:  # monthly = last weekly expiry of each month
        E=pd.DatetimeIndex(pd.Series(W).groupby([W.year,W.month]).max().values)
    E=pd.DatetimeIndex(sorted(set([days[days<=e][-1] if e<=days[-1] else e for e in E if e>=days[0]])))
    co={d:E[E>=d][0] for d in days}; ed={e:(days[days<e][-1] if len(days[days<e]) else e) for e in E}
    return dict(expiries=E, cycle_of=co, exit_day=ed)

def syn_cost(S, lots=1, prem_pct=0.007):   # 7-14 day ATM premium ~0.7% of spot
    P=S*prem_pct*LOT*lots; exch=0.0003503*4*P; sebi=0.000001*4*P
    return 80 + 0.001*2*P + exch + sebi + 0.00003*2*P + 0.18*(80+exch+sebi) + 4*1.0*LOT*lots
def fut_cost(S, lots=1):
    T=S*LOT*lots; exch=0.0000173*2*T; sebi=0.000001*2*T
    return 40 + 0.0002*T + exch + sebi + 0.00002*T + 0.18*(40+exch+sebi) + 2*1.0*LOT*lots
def ev(tr, cost=syn_cost, lots=1):
    if len(tr)==0: return dict(trades=0,net=0,pf=0,dd=0,worst=0)
    c=np.array([cost(S,lots) for S in tr.entry]); net=tr.pts.values*LOT*lots-c; eq=np.cumsum(net)
    lo=-net[net<=0].sum()
    return dict(trades=len(tr),net=round(net.sum()),pf=round(net[net>0].sum()/lo,2) if lo else 9.99,
                dd=round((eq-np.maximum.accumulate(eq)).min()),worst=round(net.min()))

BASE = dict(start=570, no_trade_after=900, sq_off=10**6, max_trades=99, days=[0,1,2,3,4], vol=0, vwap=True,
            sl="pts", sig_exit=False, exit_e21=True)
TRAILS = {"none":{}, "lock&trail: +2R->cost, trail 100":dict(trail_start=2,trail_pts=100),
          "trail from +1R, 100 behind":dict(trail_start=1,trail_pts=100), "breakeven at +2R":dict(be_at=2)}
YRS={"Y0":("2023-12-01","2024-11-19"),"Y1":("2024-11-20","2025-11-19"),"Y2":("2025-11-20","2026-11-21")}

def run_grid(df, bar_min, kinds, kills, sls, tps, trails, caps, periods):
    days=pd.DatetimeIndex(sorted(set(df.index.normalize())))
    CY={k:make_cycles(days,k) for k in kinds}
    rows=[]
    for kind,kill,sl,tp,tn,cap in itertools.product(kinds,kills,sls,tps,trails,caps):
        p=dict(BASE,bar_min=bar_min,**CY[kind],kill_cycle=kill,sl_pts=sl,rr=tp/sl,cycle_cap=cap,
               trail_start=0,trail_pts=0,be_at=0); p.update(TRAILS[tn])
        tr=backtest(df,p)
        r=dict(cycle=kind,m2m_kills_cycle=kill,sl=sl,tp=tp,trail=tn,max_cycle=cap if cap<99 else "unl")
        for k,(a,b) in periods.items():
            e=ev(tr[(tr.entry_time>=a)&(tr.entry_time<b)] if len(tr) else tr)
            r[k]=e["net"]; r[k+"_n"]=e["trades"]; r[k+"_dd"]=e["dd"]; r[k+"_pf"]=e["pf"]
        rows.append(r)
    return pd.DataFrame(rows)

if __name__=="__main__":
    df=indicators(load("60m"),2)
    R=run_grid(df,60,["weekly","biweekly","monthly"],[True,False],[40,50,60],[150,200,300],list(TRAILS),[1,2,3,5,99],
               dict(YRS,L2Y=("2024-11-20","2026-11-21")))
    R["min_year"]=R[["Y0","Y1","Y2"]].min(axis=1); R["score"]=R.L2Y/(-R.L2Y_dd).clip(lower=1)
    R.to_csv("results/biweekly_grid_60m.csv",index=False)
    pd.set_option("display.width",260); pd.set_option("display.max_columns",30)
    cols=["cycle","m2m_kills_cycle","sl","tp","trail","max_cycle","Y0","Y1","Y2","L2Y","L2Y_n","L2Y_dd","L2Y_pf","min_year","score"]
    print(R.groupby(["cycle","m2m_kills_cycle"])[["L2Y","min_year"]].median().round(0))
    for kind in ["weekly","biweekly","monthly"]:
        for kill in [True,False]:
            s=R[(R.cycle==kind)&(R.m2m_kills_cycle==kill)]
            print(f"\n{kind} kill={kill}: best by return/drawdown with every year > 0")
            print(s[s.min_year>0].sort_values("score",ascending=False)[cols].head(6).to_string(index=False))
