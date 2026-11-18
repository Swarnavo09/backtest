# backtest: NIFTY 50 intraday options backtests

Minute-level backtests of NIFTY option strategies, using modelled option prices and full Indian F&O charges.

**Latest results:** see [`results/SUMMARY.md`](results/SUMMARY.md). It covers 3 years, 4 lots, and compares the Supertrend+ADX credit spread on 5/10/15‑min candles against the previous breakout playbook.

## Run it

```bash
pip install pandas numpy pyarrow matplotlib openpyxl
python data/build_data.py     # downloads public 1-min NIFTY data, builds data/nifty_1m.parquet
python run_backtest.py        # writes everything into results/
```

## Layout

| Path | What it does |
|---|---|
| `bt/common.py` | Candles, Supertrend, ADX, ATR, NSE expiry calendar, lot sizes, Black‑Scholes pricing, charges |
| `bt/credit_spread.py` | Supertrend(10,3) + ADX(14) bull‑put / bear‑call credit‑spread rules |
| `bt/playbook_ab.py` | Previous playbook (narrow ORB + PDH/PDL breakout) as debit spreads |
| `run_backtest.py` | Runs all strategies and writes the CSV, Excel, summary and chart outputs |
| `bt/cs_lab.py` | Fast configurable Supertrend credit-spread engine for testing refinements |
| `research/` | Failure diagnosis and refinement tests, see [`research/REFINEMENT.md`](research/REFINEMENT.md) |
| `results/` | Trade logs (direction + comment per trade), daily logs, summary, equity curves |

Option premiums are modelled, not historical (see the note in `bt/common.py`). If you have historical NIFTY option‑chain data, it can be plugged into `spread_value()` to get exchange‑exact P&L.
