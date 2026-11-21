import pandas as pd, numpy as np, sys
sys.path.insert(0,".")
from biweekly import weekly_expiries
h=pd.read_pickle("data/raw_60m.pkl")["^NSEI"].dropna(); h.index=h.index.tz_localize(None)
DAYS=pd.DatetimeIndex(sorted(set(h.index.normalize())))
W=weekly_expiries(); W=pd.DatetimeIndex(sorted(set([DAYS[DAYS<=e][-1] if e<=DAYS[-1] else e for e in W if e>=DAYS[0]])))
t=pd.read_csv("algorooms/algorooms_weekly_2y.csv")
p=lambda s: pd.to_datetime(s.str.replace("Sept","Sep"),format="%d %b %Y, %H:%M")
t["et"]=p(t["Entry Time"]); t["xt"]=p(t["Exit Time"])
g=t.groupby(["et","xt"]).agg(pnl=("Profit/Loss","sum"),ex=("Exit Type","first"),s1=("Symbol","first"),tr1=("Transaction","first")).reset_index()
def cyc(d):
    d=d.normalize(); prev=W[W<d][-1]; nxt=W[W>=d][0]
    k=int(((DAYS>prev)&(DAYS<=d)).sum()); n=int(((DAYS>prev)&(DAYS<=nxt)).sum()); return k,n
g[["cday","clen"]]=[cyc(x) for x in g.et]
g["wd"]=g.et.dt.day_name().str[:3]; g["regime"]=np.where(g.et>="2025-09-01","Tue-expiry (Sep25+)","Thu-expiry (before Sep25)")
g["side"]=["LONG" if (s.endswith("CE") and tr=="BUY") or (s.endswith("PE") and tr=="SELL") else "SHORT" for s,tr in zip(g.s1,g.tr1)]
g["same_day"]=g.et.dt.date==g.xt.dt.date
pd.set_option("display.width",220)
print(g[["et","xt","wd","cday","regime","side","pnl","ex"]].to_string(index=False))
print("\nTotal",round(g.pnl.sum()),"trades",len(g))
print("\nBy regime:"); print(g.groupby("regime").pnl.agg(["count","sum",lambda s:(s>0).mean()*100]).round(0))
print("\nBy regime x weekday:"); print(g.groupby(["regime","wd"]).pnl.agg(["count","sum"]).round(0))
print("\nBy cycle day (1 = first trading day after weekly expiry):"); print(g.groupby(["regime","cday"]).pnl.agg(["count","sum",lambda s:(s>0).mean()*100]).round(0))
# streaks
s=(g.pnl<=0).astype(int); grp=(s!=s.shift()).cumsum(); st=g[s==1].groupby(grp[s==1]).agg(start=("et","first"),end=("et","last"),n=("pnl","size"),loss=("pnl","sum"))
print("\nLosing streaks (>=3):"); print(st[st.n>=3].to_string(index=False))
for lab,a in [("last 6m","2026-05-21"),("last 1y","2025-11-21"),("6-12m ago",None)]:
    x=g[g.et>=a] if a else g[(g.et>="2025-11-21")&(g.et<"2026-05-21")]
    print(lab,len(x),round(x.pnl.sum()))
print("\nFirst trade check (22 Nov 2024):"); print(t[t["Trade Date"]=="22 Nov 2024"][["Symbol","Entry Price","Exit Price","Profit/Loss"]])
g.to_csv("algorooms/weekly_trades_combined.csv",index=False)
