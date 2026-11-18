# Why the Supertrend credit spread failed, and what refinements do

**Method:** new rules were judged on **2019‑03 → 2023‑11** (development) and only then checked on the **last 3 years** (test). Everything uses 4 lots and the same modelled option prices and charges as `results/SUMMARY.md`.
Scripts: `research/refine_grid.py`, `research/alt_entries.py`. Engine: `bt/cs_lab.py`. With default settings it reproduces the original backtest: 10‑min, 409 trades, about −₹1.9 L.

## 1. Where it fails

| Finding | Evidence |
|---|---|
| **The entry has no directional edge** | After a Supertrend flip (ADX > 20, 09:25–14:00), Nifty went +30 pts before −30 pts only **48–52%** of the time, on 5, 10 and 15‑min, in both 2019–23 and 2023–26. The average follow‑through was 0–10 pts. It is a coin toss. |
| **The stop sits inside normal noise** | −1.5% = ₹600 per lot = about **32 Nifty points**. 53–55% of trades hit it, with a median of **15 minutes** after entry. |
| **Intraday credit spreads earn very little time decay** | With the 5–11 day expiry rule, the few hours a trade is held earn only a small slice of a day's decay. Meanwhile 4 fills of slippage and charges are paid on every trade. |
| **Winners are capped, losers aren't small** | Average win is about ₹2,400 vs an average loss of about ₹2,850, at a 40–45% win rate. |
| **Bullish side is worst** | On 10‑min, bullish trades lost −₹1.59 L vs −₹0.35 L for bearish. Midday entries (11:00–12:30) were the worst time slot. ADX 30–40 entries were worse than ADX 20–25. |

## 2. One change at a time (10‑min shown; 5/15‑min in `grid_*.csv`)

| Change | Dev PF | Test PF | Test net (3 yrs) |
|---|---:|---:|---:|
| Your rules (base) | 0.66 | 0.71 | −₹1.86 L |
| Entry only on the flip candle | 0.66 | 0.66 | −₹1.74 L |
| ADX > 25 | 0.69 | 0.71 | −₹1.50 L |
| Entry window 09:25–11:00 only | 0.61 | 0.78 | −₹0.82 L |
| Trade only with the day's move (≥0.3 ATR from open) | 0.73 | 0.63 | −₹1.73 L |
| **1‑hour Supertrend must agree** | 0.69 | 0.69 | −₹1.05 L |
| **Fade** the flip (opposite spread) | 0.59 | 0.53 | −₹3.30 L |
| No % stop (Supertrend close / cap / 15:15 only) | 0.71 | 0.81 | −₹1.92 L |
| Initial stop −1.0% | 0.70 | 0.58 | −₹2.64 L |
| Initial stop −2.5% | 0.68 | 0.76 | −₹1.92 L |
| No partial booking | 0.68 | 0.70 | −₹1.89 L |
| Nearest expiry (0–4 DTE) | 0.55 | 0.60 | −₹2.28 L |
| Short strike 200 pts OTM | 0.62 | 0.65 | −₹2.31 L |
| Time decay counted in market hours only (model check) | 0.91 | 0.81 | −₹1.19 L |

PF = profit factor (gross wins ÷ gross losses). Above 1.0 means profitable.

**No single change makes it profitable.** Changing stop size, partial booking or the Supertrend exit can't fix an entry that is 50/50. Fading is worse, because a coin toss faded is still a coin toss, with costs on top.

## 3. Different entries, same credit‑spread structure

| Strategy | Dev PF | Test PF | Test net |
|---|---:|---:|---:|
| Breakout signals (narrow ORB + PDH/PDL) → Bull Put / Bear Call | 0.93 | 0.89 | −₹1.39 L |
| Range‑day iron condor (narrow first hour, shorts ±0.5 ATR, 10:15–15:15) | 0.00 | 0.00 | −₹4.68 L |
| **Combo: 1h Supertrend agrees + 09:25–11:00 + ADX > 25** (10‑min) | 0.62 | 0.96 | −₹5k |

The iron condor loses on nearly every trade. About 5 hours of time decay at 5+ days to expiry is worth roughly 2 pts, while 8 legs of slippage cost about 4 pts.

## 4. Best case for the refined version

The 10‑min combo, with time decay counted only in market hours, is the most optimistic modelling choice:

| Assumption | Dev PF | Test PF | Net per year (4 lots) |
|---|---:|---:|---:|
| 0.5‑pt slippage per leg | 1.03 | 1.15 | ₹1.3k / ₹6.6k |
| 0.25‑pt slippage per leg | 1.19 | 1.33 | ₹6.8k / ₹13.1k |

That is about 33 trades a year and roughly **1–8% a year on ₹1.6 L margin**. It only turns positive under favourable assumptions, so treat it as **marginal and unproven**.

## 5. Recommendation

1. **Don't trade the original rules.** The loss is structural, not a matter of parameters.
2. If you keep Supertrend, the only version worth paper‑trading is:
   - 10‑min chart, Supertrend(10,3) flip, **ADX > 25**
   - **1‑hour Supertrend the same colour**
   - entries **09:25–11:00 only**, one trade a day
   - the rest of your rules unchanged (spread, −1.5% ladder, +3% partial, ₹5k cap, 15:15)

   Paper‑trade it for 2–3 months and record **actual fills**. It only works if your real slippage is ≤0.25 pt per leg and real premiums decay faster during market hours than the model assumes.
3. The edge that held up in the research is **breakouts from compression** (narrow opening range, previous‑day high/low). Intraday option spreads eat most of it through slippage, charges and time decay. Two ways that could keep more of it, neither tested yet:
   - trade the signals with fewer fills (single‑leg or futures);
   - hold credit spreads past one session, so overnight time decay works for you.
4. Get real historical option prices. Every option P&L here is modelled with Black‑Scholes, and the conclusions above are most sensitive to slippage and to how fast time decay really happens during market hours.
