"""Exit refinements for the positional setup + Futures vs Synthetic Futures (Buy ATM CE + Sell ATM PE)
after all charges. Synthetic gross P&L == futures gross P&L (put-call parity, delta 1); only costs differ."""
import pandas as pd, numpy as np
from nifty_fut_bt import *
df = indicators(load("60m"), 2)
B = dict(bar_min=60, start=570, no_trade_after=900, sq_off=10**6, max_trades=1, days=[0,1,2,3,4],
         vol=0, vwap=True, sl="pts", sl_pts=50, rr=4, sig_exit=False)

def monthly_expiries():
    out=[]
    for m in pd.period_range("2023-11","2027-01",freq="M"):
        last=m.to_timestamp(how="end").normalize()
        wd = 1 if last >= pd.Timestamp("2025-09-01") else 3   # Tue from Sep-2025, Thu before
        while last.dayofweek!=wd: last-=pd.Timedelta(days=1)
        out.append(last)
    return pd.DatetimeIndex(out)
EXP = monthly_expiries()

def rolls(tr):
    r=[]
    for e,x in zip(tr.entry_time, tr.exit_time):
        exp = EXP[EXP >= e.normalize()+pd.Timedelta(days=3)][0]    # within 3 days of expiry -> next month
        r.append(int(((EXP > exp - pd.Timedelta(days=1)) & (EXP < x.normalize())).sum()))
    return np.array(r)

def fut_cost_rs(S, stt=0.0002, slip=1.0):
    T=S*LOT; exch=0.0000173*2*T; sebi=0.000001*2*T
    return 40 + stt*T + exch + sebi + 0.00002*T + 0.18*(40+exch+sebi) + 2*slip*LOT

def syn_cost_rs(S, stt=0.001, slip=1.0, prem_pct=0.011):
    P=S*prem_pct*LOT; exch=0.0003503*4*P; sebi=0.000001*4*P
    return 80 + stt*2*P + exch + sebi + 0.00003*2*P + 0.18*(80+exch+sebi) + 4*slip*LOT

def evaluate(tr, kind, **kw):
    n_roll = rolls(tr)
    f = fut_cost_rs if kind=="fut" else syn_cost_rs
    c = np.array([f(S, **kw) for S in tr.entry]) * (1 + n_roll)
    net = tr.pts.values*LOT - c
    eq = np.cumsum(net); dd = (eq - np.maximum.accumulate(eq)).min()
    return dict(trades=len(tr), net_rs=round(net.sum()), pf=round(net[net>0].sum()/-net[net<=0].sum(),2),
                maxdd=round(dd), cost_rs=round(c.sum()), cost_per_trade=round(c.mean()), rolls=int(n_roll.sum()))

exits = {
 "Base: SL50 / TP200":{},
 "SL50 / TP250 (1:5)":dict(rr=5),
 "+ Breakeven after +100":dict(be_at=2),
 "+ Breakeven after +150":dict(be_at=3),
 "+ Trail 100 after +100":dict(trail_start=2, trail_pts=100),
 "+ Trail 75 after +150":dict(trail_start=3, trail_pts=75),
 "No TP, trail 100 after +100":dict(rr=50, trail_start=2, trail_pts=100),
 "No TP, trail 150 after +150":dict(rr=50, trail_start=3, trail_pts=150),
 "+ Exit on 1H EMA9<EMA21":dict(exit_ema=True),
 "+ Exit on SuperTrend flip":dict(exit_st=True),
 "+ Exit on VWAP cross":dict(exit_vwap=True),
 "+ Time stop 3 days (21 bars)":dict(time_stop=21),
 "+ Time stop 5 days (35 bars)":dict(time_stop=35),
}
rows=[]; trades={}
for name,v in exits.items():
    tr=backtest(df,dict(B,**v)); trades[name]=tr
    row={"exit":name}
    for per,(a,b) in {"Y1":("2024-11-20","2025-11-19"),"Y2":("2025-11-20","2026-11-21"),"Y0":("2023-12-01","2024-11-19")}.items():
        row[per]=evaluate(tr[(tr.entry_time>=a)&(tr.entry_time<b)],"fut")["net_rs"]
    t2=tr[tr.entry_time>="2024-11-20"]
    e=evaluate(t2,"fut"); row.update(fut_2y=e["net_rs"], fut_pf=e["pf"], fut_dd=e["maxdd"], win=round((t2.pts*LOT>fut_cost_rs(25000)).mean()*100,1))
    rows.append(row)
R=pd.DataFrame(rows).set_index("exit"); pd.set_option("display.width",250)
print("EXIT REFINEMENTS (futures costs, 1 lot):"); print(R.to_string()); R.to_csv("results/exit_refinements.csv")

print("\nFUTURES vs SYNTHETIC (2y, Nov24-Nov26):")
cmp=[]
for name in ["Base: SL50 / TP200","SL50 / TP250 (1:5)","+ Trail 100 after +100","No TP, trail 150 after +150"]:
    t2=trades[name][trades[name].entry_time>="2024-11-20"]
    for lab,kind,kw in [("Futures","fut",{}),("Synthetic (monthly ATM)","syn",{}),
                        ("Futures STT 0.05% stress","fut",dict(stt=0.0005)),
                        ("Synthetic STT 0.15% + 2pt slip/leg","syn",dict(stt=0.0015,slip=2.0))]:
        cmp.append(dict(exit=name, instrument=lab, **evaluate(t2,kind,**kw)))
C=pd.DataFrame(cmp); print(C.to_string(index=False)); C.to_csv("results/futures_vs_synthetic.csv",index=False)
print("gross 2y base:", round(trades["Base: SL50 / TP200"].query("entry_time>='2024-11-20'").pts.sum()*LOT))
