# Nifty Futures: intraday backtest of the "NIFTY SPREAD" conditions

Rules tested (taken from the Algorooms strategy):
- Long: Close > SuperTrend(10,3), Close > EMA21, EMA9 > EMA21, EMA9 > EMA21 on the higher timeframe. Short is the mirror.
- Exit: higher-timeframe EMA9/21 cross, SL, TP or square-off at 15:10. Entries 09:30–15:00, 1 trade a day, Mon/Tue/Thu.
- Added: SL always on (ATR or SuperTrend based), target 1:2 / 1:3 / 1:4, volume filter (relative volume), VWAP filter.
- 1 lot = 65. Costs are included: brokerage, 0.02% STT, exchange fees, GST, stamp duty and 1 pt slippage per side, about 10 pts a round trip.

Data limits: Yahoo is the only reachable feed. It has 2 years only at 60-min bars and 15-min only for the last 60 days.
Volume is the turnover of the top-15 Nifty stocks, used as a stand-in for futures volume. Spot price stands in for the futures price.

Files: `nifty_fut_bt.py` (engine), `summary.py`, `run_grid.py`, `run_grid2.py`; results are in `results/`.
Run: `python3 summary.py` (data is in `data/`, refetch with yfinance).
