import pandas as pd
from nifty_fut_bt import *
df=indicators(load("60m"),2)
b=dict(bar_min=60, start=570, no_trade_after=900, sq_off=910, max_trades=1, days=[0,1,3], vol=0, vwap=False, sl=1.0, rr=2, sig_exit=True)
cfg={"A. Your rules as-is, 1:2":{},
     "B. + Volume (RVOL>1.2)":dict(vol=1.2),
     "C. + Volume + VWAP":dict(vol=1.2,vwap=True),
     "D. C with 1:3":dict(vol=1.2,vwap=True,rr=3),
     "E. Fresh signal only, 1:3":dict(mode="fresh",rr=3),
     "F. VWAP/EMA21 pullback, 1:2":dict(mode="pullback",vol=1.0),
     "G. A, all 5 days, 2 trades/day":dict(days=[0,1,2,3,4],max_trades=2)}
rows=[]
for k,v in cfg.items():
    tr=backtest(df,dict(b,**v)); tr=tr[tr.entry_time>="2024-11-20"]
    s=stats(tr); s["gross_rs"]=round(tr.pts.sum()*LOT); rows.append(dict(name=k,**s))
    if k.startswith("A"): tr.to_csv("results/trades_original_rules_60m.csv",index=False)
R=pd.DataFrame(rows).set_index("name"); print(R.to_string()); R.to_csv("results/summary_intraday_2y.csv")
