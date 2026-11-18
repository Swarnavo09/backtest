# Blaze Butterfly backtest (NIFTY, 2-lot)

Rule-based 1:2:1 broken-wing put butterfly, traded **2x**: BUY 2 lots K1, SELL 4 lots K2 (= K1 − 200), BUY 2 lots K3 (= K2 − 400).

```bash
pip install pandas openpyxl
python blaze_backtest.py                          # 2025-01-01 .. today, Rs 1,00,000 margin per 1:2:1 set
python blaze_backtest.py --margin-per-set 150000  # use your broker's actual basket margin
python blaze_backtest.py --fill-at-levels         # book target/SL exactly at +1.5% / -1%
```

The script downloads the free NSE F&O bhavcopies (end-of-day data) into `data/fo/` and writes the results to `results/`:
`weekly_trades.csv`, `monthly_summary.csv`, `yearly_summary.csv` and `blaze_butterfly_backtest.xlsx`.

| Rule | How it is modelled |
|---|---|
| Entry Monday 3:16 / 3:35 PM | Monday closing price (first trading day of the week if Monday is a holiday) |
| Expiry | First weekly expiry after that week's Friday (skips the nearest expiry) |
| Strikes | ATM − 200, rolled lower in 50-pt steps until net credit ≤ 0.6 % of margin; always a net credit, otherwise the week is skipped (`--allow-debit` allows a debit ≤ 0.7 %) |
| Target / SL | +1.5 % / −1 % of margin, checked on each day's closing prices |
| Time exit | Friday close (or the last trading day of the week) |
| Charges | ₹20/order, STT 0.1 % sell side, NSE txn 0.03503 %, SEBI, stamp, 18 % GST (`--no-costs` turns them off) |

EOD data cannot show intraday target/SL touches or the 2:30 PM exit. The default mode books exits at the close, which overstates gaps.
`--fill-at-levels` books every touch at exactly the level, which is optimistic. The true result lies between the two.
