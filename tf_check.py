"""Timeframe check (15m / 30m / 1H) on the only common window (last ~60 days), plus day-by-day and intraday checks on 1H (3 years)."""
import pandas as pd, numpy as np
from weekly_combined import *
def load_tf(tf):
    if tf=="60m": return load("60m")
    d=load("15m")
    if tf=="15m": return d
    g=d.groupby(d.index.floor("D"))
    out=[]
    for day,x in g:
        x=x.copy(); x["grp"]=((x.index.hour*60+x.index.minute-555)//30)
        y=x.groupby("grp").agg(Open=("Open","first"),High=("High","max"),Low=("Low","min"),Close=("Close","last"),Volume=("Volume","sum"))
        y.index=[day+pd.Timedelta(minutes=555+30*int(k)) for k in y.index]; out.append(y)
    return pd.concat(out)
A=dict(sl_rs=8000,tp_rs=40000,lock=(16000,300,1600,1600),cap=2)
print("== Timeframes, window 28 Aug - 20 Nov 2026 (same rules, Thu/Fri entries vs any day)")
for tf,bar in [("15m",15),("30m",30),("60m",60)]:
    df=indicators(load_tf(tf),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
    for ed in [(2,3),(1,2,3,4)]:
        for em in ["exp","intra"]:
            tr=run(df,bar,E,co,pin,A["sl_rs"],A["tp_rs"],A["lock"],A["cap"],ed,em,True)
            print(f"  {tf:4s} entry_days={str(ed):12s} {'positional' if em=='exp' else 'intraday  '}",evw(tr[tr.entry_time>="2026-08-28"]))
print("\n== 1H, 3 years: each entry day alone, by year")
df=indicators(load("60m"),2); days=pd.DatetimeIndex(sorted(set(df.index.normalize()))); E,co,pin=week_cycles(days)
for ed,lab in [((1,),"day 1 (Wed now / Fri before Sep-25)"),((2,),"day 2 (Thu now / Mon before)"),((3,),"day 3 (Fri now / Tue before)"),((4,),"day 4 (Mon now / Wed before)")]:
    tr=run(df,60,E,co,pin,A["sl_rs"],A["tp_rs"],A["lock"],A["cap"],ed,"exp",True)
    print(f"  {lab:38s}",[evw(tr[(tr.entry_time>=a)&(tr.entry_time<b)])["net"] for a,b in YRS.values()],"last 6m",round(tr[tr.entry_time>="2026-05-20"].net.sum()))
print("\n== 1H, 3 years: intraday (exit 15:10 same day) vs positional, Thu/Fri")
for em in ["exp","intra"]:
    tr=run(df,60,E,co,pin,A["sl_rs"],A["tp_rs"],A["lock"],A["cap"],(2,3),em,True)
    print(" ",em,[evw(tr[(tr.entry_time>=a)&(tr.entry_time<b)])["net"] for a,b in YRS.values()])
