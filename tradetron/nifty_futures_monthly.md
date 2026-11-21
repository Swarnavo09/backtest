# Strategy Spec — NIFTY Futures Monthly
## METADATA
| Field | Value |
| Strategy name | NIFTY Futures Monthly |
| Description | Monthly NIFTY synthetic future (ATM CE + ATM PE, current month, 2 lots). Enters on a 1-hour trend signal (SuperTrend 10,3; close vs EMA21; EMA9 vs EMA21; EMA18 vs EMA42; close vs VWAP; close beyond previous-day high/low) only when India VIX is 18 or lower, Tuesday to Friday, from the 2nd calendar day after the monthly expiry until 5 calendar days before the next one. Exits on total P&L: stop loss Rs 6,500, target Rs 32,500, trailing stop that arms at Rs 13,000 profit and trails Rs 12,700 behind the best profit; any open position is closed at 15:10 one day before expiry. Rupee levels assume multiplier 1. |
| Default underlying | NIFTY 50 |
| Price execution | Market Price |
| Reactivation minutes | 60 |
| Capital required | 600000 |
| Exit shorts first | Yes |
## UNIVERSAL EXIT (OR-joined)
- `PNL()` `<=` `Number(-6500)`
- `PNL()` `>=` `Number(32500)`
- (group, AND-joined)
  - `Max Profit()` `>=` `Number(13000)`
  - `Math Operation(Max Profit(), PNL(), '-')` `>=` `Number(12700)`
- (group, AND-joined)
  - `Days Difference (D2-D1)(Today('NSE'), Current Month Expiry('NIFTY 50', 0))` `<=` `Number(1)`
  - `Time('NSE')` `>=` `Number(1510)`
## SETS
### Set 1: Long
#### Identity
| Field | Value |
| Set name | Long |
| Underlying | NIFTY 50 |
| List | 0 |
#### Entry condition (AND-joined)
- `Time('NSE')` `>=` `Number(1001)`
- `Time('NSE')` `<=` `Number(1500)`
- `Week Day('NSE')` `!=` `Number(1)`
- `Days Difference (D2-D1)(Previous Expiry('NIFTY 50', 'Month', 0), Today('NSE'))` `>=` `Number(2)`
- `Days Difference (D2-D1)(Today('NSE'), Current Month Expiry('NIFTY 50', 0))` `>=` `Number(5)`
- `Open Positions Detail('All', 'All', 'NIFTY 50', 'count')` `==` `Number(0)`
- `LTP(Instrument Name('NSE_IDX,INDIA VIX,,,,,'))` `<=` `Number(18)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `>` `Position(SUPERTREND(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All'), 10, 3), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `>` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 21), -1)`
- `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 9), -1)` `>` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 21), -1)`
- `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 18), -1)` `>` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 42), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `>` `Position(VWAP Series(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h'), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `>` `Position(HIGH(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), 'day', 'All')), -1)`
#### Legs
| # | Buy/Sell | Underlying | Type | Expiry | Strike | Qty | Product |
| 1 | B | NIFTY 50 | CE | Current Month | `ATM("NIFTY 50", 0)` | 2 | NRML |
| 2 | S | NIFTY 50 | PE | Current Month | `ATM("NIFTY 50", 0)` | 2 | NRML |
### Set 2: Short
#### Identity
| Field | Value |
| Set name | Short |
| Underlying | NIFTY 50 |
| List | 0 |
#### Entry condition (AND-joined)
- `Time('NSE')` `>=` `Number(1001)`
- `Time('NSE')` `<=` `Number(1500)`
- `Week Day('NSE')` `!=` `Number(1)`
- `Days Difference (D2-D1)(Previous Expiry('NIFTY 50', 'Month', 0), Today('NSE'))` `>=` `Number(2)`
- `Days Difference (D2-D1)(Today('NSE'), Current Month Expiry('NIFTY 50', 0))` `>=` `Number(5)`
- `Open Positions Detail('All', 'All', 'NIFTY 50', 'count')` `==` `Number(0)`
- `LTP(Instrument Name('NSE_IDX,INDIA VIX,,,,,'))` `<=` `Number(18)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `<` `Position(SUPERTREND(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All'), 10, 3), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `<` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 21), -1)`
- `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 9), -1)` `<` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 21), -1)`
- `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 18), -1)` `<` `Position(EMA(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), 42), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `<` `Position(VWAP Series(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h'), -1)`
- `Position(CLOSE(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), '1h', 'All')), -1)` `<` `Position(LOW(Symbol(Instrument Name('NFO,NIFTY 50,Current Month,,,,'), 'day', 'All')), -1)`
#### Legs
| # | Buy/Sell | Underlying | Type | Expiry | Strike | Qty | Product |
| 1 | B | NIFTY 50 | PE | Current Month | `ATM("NIFTY 50", 0)` | 2 | NRML |
| 2 | S | NIFTY 50 | CE | Current Month | `ATM("NIFTY 50", 0)` | 2 | NRML |
