# NIFTY Supertrend Credit‑Spread Strategy (final rules, plain English)

## 1. Market and size
- **Instrument:** NIFTY 50 weekly options. Intraday only: everything is closed by 3:15 PM.
- **Size:** 4 lots on every trade.
- **Expiry:** always the **next weekly expiry**, never the current week's. *Example:* if this week's expiry is Tuesday 10th, trade the Tuesday 17th contracts, every day of the week, including expiry day itself.

> **Version 2 (tuned):** Supertrend changed from (10, 3) to **(10, 2)**, and the ADX threshold raised from 25 to **30**. Both were tuned on 2019 → Nov 2024 data only (`research/tune_indicators.py`, `research/tune_exits.py`). Result: `results/refined/FINAL_RESULTS.md`.

## 2. Chart setup
- **15‑minute** NIFTY spot chart: Supertrend (**10, 2**) and ADX (14).
- **1‑hour** NIFTY spot chart: Supertrend (**10, 2**).

## 3. Days you skip
- Skip the day if there is **no Supertrend flip on the 15‑min chart between 9:30 and 11:00 AM**.
- Skip the day if **the last 3 trading days you traded all ended in a loss**. Sit out the next day and resume the day after.
- If the flip happens but any entry condition below fails, there is no trade. That is the "setup not good" skip.

## 4. Entry: check only when a 15‑minute candle closes
All of these must be true:
1. The 15‑min Supertrend **flipped colour today**, and the candle closed on the new side of the line.
2. **ADX (14) is above 30.**
3. The **1‑hour Supertrend is the same colour** as the new 15‑min colour.
4. The candle closes **between 9:30 and 11:00 AM**.

| Signal | Direction | Trade |
|---|---|---|
| Red → green | **Bullish** | **Bull Put Spread:** sell the put about 100 pts below spot (round down to the 50 strike), buy the put 500 pts below that |
| Green → red | **Bearish** | **Bear Call Spread:** sell the call about 100 pts above spot (round up to the 50 strike), buy the call 500 pts above that |

**Order of legs:** buy the protective leg first, then sell the short leg. When exiting, buy back the short leg first, then sell the protective leg.

## 5. Stop loss, target and trailing (₹ for all 4 lots together, on combined MTM of both legs)

| Stage | Rule |
|---|---|
| Initial stop loss | **−₹5,000** |
| Target | **+₹15,000**, close all 4 lots (**reward:risk 1:3**) |
| Profit lock | When MTM reaches **+₹5,000** (1R), move the stop to **+₹500**, which covers charges |
| Trailing | After that, the stop moves up by **50% of every further rupee of profit**: stop = ₹500 + 50% × (highest MTM − ₹5,000). *Example:* best MTM ₹9,000 → stop ₹2,500. Best MTM ₹13,000 → stop ₹4,500. |
| Time exit | Close everything at **3:15 PM** |

## 6. Daily limits
- **Maximum 2 trades a day.**
- A 2nd trade needs all of:
  - the first trade is closed;
  - a **new flip in the opposite direction** has appeared by 11:00 AM, with all the entry conditions met;
  - **room for a full ₹5,000 stop** remains under the daily limit.
- **Daily loss limit −₹10,000** (booked + open). If it is hit, close everything and stop for the day.
- After a losing first trade (about −₹5,500 with costs), there is no room for another full stop, so **one loss = done for the day.**

## 7. How the numbers were chosen
- The stop, target and trail were chosen on **2019 → Nov 2024 data only** (96 combinations, `research/select_exits.py`).
- The last 2 years were **not** used for choosing, so they are an honest test.
- On the selection data, the best settings only **broke even** (profit factor 1.00). No stop/target combination made this entry clearly profitable. Treat it as a strategy to **paper‑trade first**.
