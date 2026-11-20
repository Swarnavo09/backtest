import json, pandas as pd, numpy as np
from biweekly import weekly_expiries
h=pd.read_pickle("data/raw_60m.pkl")["^NSEI"].dropna(); h.index=h.index.tz_localize(None)
DAYS=pd.DatetimeIndex(sorted(set(h.index.normalize())))
W=weekly_expiries(); W=pd.DatetimeIndex([DAYS[DAYS<=e][-1] if e<=DAYS[-1] else e for e in W if e>=DAYS[0]])
M=pd.DatetimeIndex(pd.Series(W).groupby([W.year,W.month]).max().values)
def tdays_between(a,b):  # trading days from a to b (b>=a)
    return int(((DAYS>a)&(DAYS<=b)).sum())
def feats(et,xt):
    d=et.normalize(); nm=M[M>=d][0]; pm=M[M<d][-1] if (M<d).any() else d; nw=W[W>=d][0]
    return dict(wd=int(et.dayofweek), hr=int(et.hour), dom=int(et.day), dte=tdays_between(d,nm), dse=tdays_between(pm,d),
                dtw=tdays_between(d,nw), on=int(xt.normalize()>d), hold=round((xt-et).total_seconds()/3600,1),
                xwd=int(xt.dayofweek), mon=et.strftime("%Y-%m"))
out={}
# A: Algorooms report
t=pd.read_csv("algorooms/algorooms_trades_2y_v2.csv")
p=lambda s: pd.to_datetime(s.str.replace("Sept","Sep"),format="%d %b %Y, %H:%M")
t["et"]=p(t["Entry Time"]); t["xt"]=p(t["Exit Time"])
g=t.groupby(["et","xt"]).agg(pnl=("Profit/Loss","sum"),ex=("Exit Type","first"),s1=("Symbol","first"),tr1=("Transaction","first")).reset_index()
A=[]
for r in g.itertuples():
    side = 1 if (r.s1.endswith("CE") and r.tr1=="BUY") or (r.s1.endswith("PE") and r.tr1=="SELL") else -1
    A.append(dict(et=r.et.strftime("%Y-%m-%d %H:%M"),xt=r.xt.strftime("%Y-%m-%d %H:%M"),side=side,gross=round(r.pnl),cost=760,
                  exit="M2M" if r.ex=="M2M_SQUAREOFF" else "COND",**feats(r.et,r.xt)))
out["algo"]=dict(name="Algorooms report: monthly, 2 lots",lots=2,trades=A)
# B: my bi-weekly synthetic backtest (1 lot -> scaled to 2 lots)
b=pd.read_csv("results/trades_biweekly_synthetic_final.csv",parse_dates=["entry_time","exit_time"])
B=[]
for r in b.itertuples():
    et=r.entry_time+pd.Timedelta(hours=1); xt=r.exit_time+pd.Timedelta(hours=1)   # bar start -> actual (bar close) time
    B.append(dict(et=et.strftime("%Y-%m-%d %H:%M"),xt=xt.strftime("%Y-%m-%d %H:%M"),side=int(r.side),gross=round(r.gross*2),cost=round(r.cost*2-80*2),
                  exit=r.reasons.split("/")[0],**feats(et,xt)))
out["biw"]=dict(name="My backtest: bi-weekly legs, 2 lots",lots=2,trades=B)
json.dump(out,open("dashboard/data.json","w"))
# quick analysis print
for k,v in out.items():
    df=pd.DataFrame(v["trades"]); df["net"]=df.gross-df.cost
    print("\n==",v["name"],len(df),"trades, net",df.net.sum())
    for col,lab in [("wd","weekday"),("hr","entry hour"),("dte","trading days to monthly expiry"),("dse","trading days since expiry"),("dtw","days to weekly expiry"),("on","overnight")]:
        x=df.groupby(col).net.agg(["count","sum"]).T; print(lab, x.to_dict())
