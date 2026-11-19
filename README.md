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

## One-year test at 1 vs 4 lots (MIS: entries until 14:00, exit 14:45)

```bash
python fetch_upstox.py 2025-11-01 2026-11-18   # Upstox public candles, no key needed
python run_year.py                              # -> results/year_*.csv, year_summary.json
python build_report.py
```

258 sessions (3 Nov 2025 - 18 Nov 2026), 1,152 combinations at 4 lots:

| View | 1 lot | 4 lots |
|---|---|---|
| Fixed 10-min setup from the first test | -Rs 19,992 | -Rs 32,389 |
| Walk-forward (re-pick monthly from last 3 months) | -Rs 19,915 | -Rs 27,557 |
| Best combination in hindsight (10m, hedge 300, SL 40, trail) | -Rs 5,466 | +Rs 29,112 |

4 lots cuts cost per lot per trade from about Rs 263 to Rs 192 (only brokerage is
fixed per order), but the setup earns about Rs 144 per lot per trade before costs.
Slippage is the deciding factor: at 0.25 pt per leg instead of 0.5 pt, the fixed setup
at 4 lots makes +Rs 11,291 for the year.

## v3: weekly/daily bias + real option prices (current strategy)

```bash
python fetch_upstox.py 2022-01-01 2026-11-18   # then save the 5m file as data/nifty_5m_5y.csv
python fetch_bhav.py                            # NSE bhavcopies -> real Nifty option premiums
python calibrate.py                             # 70% trading-time / 30% calendar-time decay fits real prices
python run_v3.py mix70v                         # 9,600 setups on 15-minute candles, 2022-2026
python select_v3.py mix70v                      # choose on 2022-24 only, stress-test on 2025-26
python build_report_v3.py mix70v                # report/index.html
```

Rules (consensus of the 461 setups that were profitable in each of 2022, 2023, 2024):
trade bullish only when this week's and today's candles are green (bearish when both red);
trigger = Supertrend(10,3) + EMA 9/21 + MACD(12,26,9) on 15-minute candles, signal 09:30-13:30;
sell ATM, hedge 300 points away (bull put / bear call), nearest weekly incl. expiry day;
SL 120 Nifty points, otherwise hold to 14:45; max 1 trade a day; 6 lots.

Result at 6 lots after all charges and 0.5 pt slippage per leg per side:
2022-24 +Rs 4.73 lakh (PF 1.20), 2025-Nov 2026 +Rs 6.40 lakh (PF 1.43), every year positive.
About 77% of the profit comes from expiry-day trades. Intraday option prices are modelled
from real previous-day closing premiums with VIX-driven IV, not recorded tick data.
