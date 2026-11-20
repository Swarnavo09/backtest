from check_15m import *
d=load("15m"); x=d.copy(); x["st"],x["st_dir"]=supertrend(x,40,3); x["e9"],x["e21"]=ema(x.Close,36),ema(x.Close,84); x["h9"],x["h21"]=ema(x.Close,72),ema(x.Close,168)
x["atr"]=atr(x,56); day=x.index.normalize(); tp=(x.High+x.Low+x.Close)/3
x["vwap"]=(tp*x.Volume).groupby(day).cumsum()/x.Volume.groupby(day).cumsum(); x["rvol"]=1.0; x["d_up"]=True
for co in [False,True]:
    t=backtest(x,dict(P,**C15,bar_min=15,close_only=co)); show(f"15m x4 lengths close_only={co} Aug28-Nov20",t,"2026-08-28","2026-11-21"); show("   last 2m",t,"2026-09-20","2026-11-21")
