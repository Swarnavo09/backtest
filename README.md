# Nifty Trend Spread backtest

Hedged Nifty option selling: on a bullish EMA + MACD + Supertrend confluence open a
**bull put spread** (sell PE, buy a lower PE as hedge); on a bearish confluence open a
**bear call spread** (sell CE, buy a higher CE). Stop-loss and target are in Nifty spot
points with target = 2 x stop. Tested on 5, 10 and 15 minute candles.

## Run

```bash
pip install yfinance pandas numpy
python fetch_data.py      # Nifty 5m candles + India VIX (Yahoo keeps ~60 days; re-run to grow history)
python run_backtest.py    # stage 1 (rules as described) + stage 2 (structural fixes) grids -> results/
python build_report.py    # report/index.html
```

## Files

- `strategy.py` - indicators, Black-Scholes spread pricing, Indian F&O charges, trade engine
- `run_backtest.py` - parameter grids with an in-sample / held-back split
- `build_report.py`, `report/` - the HTML report
- `results/` - every combination (`grid_stage*.csv`) and the trades of each chosen setup

## Result on 59 sessions (24 Aug - 18 Nov 2026)

- Rules as described (ATM short, 200-pt hedge): 0 of 2,160 combinations profitable after costs.
- With fixes (1-hour Supertrend filter, sell 100 ITM, 1-2 trades/day, trailing exits):
  0.8% of 8,640 combinations profitable over all days and none profitable in both the
  parameter-picking period and the held-back period.
- Main reason: an ATM spread earns only about a quarter of a rupee per Nifty point per
  unit, so the ~Rs 250 per-trade cost of 4 orders eats the edge.

Option prices are modelled (Black-Scholes with prior-day India VIX), not real traded
premiums. Research only, not investment advice.
