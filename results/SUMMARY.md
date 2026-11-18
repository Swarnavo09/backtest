# NIFTY options backtest: 18 Nov 2023 → 18 Nov 2026 (3 years), 4 lots

Strategies compared:
- **CS‑5m / CS‑10m / CS‑15m**: your Supertrend(10,3) + ADX(14) credit‑spread rules, run on 5, 10 and 15‑minute candles.
- **Prev A+B**: the previous playbook (narrow 30‑min opening‑range breakout + previous‑day high/low breakout), expressed as debit spreads.

All P&L is in ₹ for 4 lots, after slippage (0.5 pt per leg per fill) and full Indian F&O charges. The lot size is the one NSE had in force on each date: 50, then 75 from 20‑Nov‑2024, then 65 from 2026.

## Result

| | CS‑5m | CS‑10m | CS‑15m | Prev A+B (debit) |
|---|---:|---:|---:|---:|
| Trades | 614 | 409 | 306 | 519 |
| Win rate | 39.9% | 44.5% | 43.1% | 38.5% |
| **Net P&L** | **−₹4,46,408** | **−₹1,94,699** | **−₹2,26,765** | **−₹1,34,073** |
| Return on ₹1.6 L margin | −279% | −122% | −142% | −84% |
| Avg win / avg loss | 2,418 / −2,815 | 2,501 / −2,863 | 2,036 / −2,848 | 3,890 / −2,859 |
| Profit factor | 0.57 | 0.70 | 0.54 | 0.85 |
| Max drawdown | −₹4.44 L | −₹2.18 L | −₹2.32 L | −₹1.75 L |
| Profitable months | 11% | 32% | 24% | 35% |
| Charges paid | ₹1.21 L | ₹0.80 L | ₹0.60 L | ₹1.23 L |
| **Bullish** trades / net / win% | 309 / −₹2.97 L / 37.5% | 212 / −₹1.59 L / 40.1% | 155 / −₹1.25 L / 40.6% | 259 / −₹1.62 L / 36.3% |
| **Bearish** trades / net / win% | 305 / −₹1.50 L / 42.3% | 197 / −₹0.35 L / 49.2% | 151 / −₹1.02 L / 45.7% | 260 / **+₹0.28 L** / 40.8% |

**Ranking: Prev A+B (least bad) > CS‑10m > CS‑15m > CS‑5m.** None of the four was profitable over these 3 years. Among your three timeframes, **10‑min is the best** (it loses the least), and 5‑min is clearly the worst.

## Why it loses

1. **The −1.5% stop is narrower than normal market noise.** ₹600 per lot is only 8–12 points of spread value, which is about 25–40 Nifty points, roughly one ordinary 10‑min candle. **53–55% of all trades hit the initial stop.**
2. **The entry signal has no edge.** A Supertrend flip happens *after* the move. Widening the initial stop to −3% raised the win rate to 57–59%, but the result got *worse* (CS‑10m −₹2.08 L, CS‑5m −₹5.78 L).
3. **The results don't depend on my cost assumptions.** With **zero** slippage it still loses on every timeframe (5m −₹0.69 L, 10m −₹0.20 L, 15m −₹0.65 L).
4. **5‑min flips far more often** (614 trades), so it pays the most in charges and gets whipsawed the most.

The previous A+B playbook is break‑even before charges (−₹11.6k gross). At 0.25‑pt slippage it is about flat (−₹13k), and with perfect fills it would make +₹1.07 L. On the index it made money in these years, but option spreads, charges and time decay eat a thin intraday edge. Its bearish trades were profitable (+₹28k). Bullish trades lost money in **every** strategy.

## Cost sensitivity (net ₹, 4 lots)

| Slippage per leg | CS‑5m | CS‑10m | CS‑15m | Prev A+B |
|---|---:|---:|---:|---:|
| 0.5 pt (base) | −4,46,408 | −1,94,699 | −2,26,765 | −1,34,073 |
| 0.25 pt | −2,62,455 | −85,588 | −1,44,934 | −13,385 |
| 0 (perfect fills) | −69,119 | −19,568 | −64,577 | +1,07,290 |

## How this was modelled (read before trusting the numbers)

- **Spot data:** 1‑minute NIFTY 50 spot data. Supertrend and ADX are computed on continuous 5/10/15‑min candles.
- **Entries and Supertrend exits** happen only at candle close. Stops, the trailing ladder, the +3% partial booking (3 lots booked, 1 runner) and the ₹5,000 daily cap are checked every minute.
- **Option prices are *modelled*** (Black‑Scholes) because no historical option‑chain data was available.
  - Implied volatility = 1.2 × recent realised volatility (a stand‑in for India VIX), plus a put skew.
  - IV is held flat through each day. Real intraday IV spikes would hurt short spreads further on bad days.
- **Your rules, and the assumptions I made where they were open:**
  - Margin is ₹40,000 per lot, so 1.5% = ₹600 per lot.
  - Days with no trade don't count toward the 3‑day losing streak.
  - The daily cap includes open losses.
  - The entry may come on any candle after today's flip while ADX > 20. A run that enters on the flip candle only gave −₹1.84 L on 10‑min, essentially the same.
  - Expiry: nearest weekly if it is ≥5 calendar days away, otherwise the next one. This matches your "Wed/Thu this week, Fri–Tue next week" rule for Tuesday expiries, and the same 5‑day rule is used in the Thursday‑expiry years.

Trade‑by‑trade logs, each with a **Bullish/Bearish direction and a plain‑English comment**, are in `trades_*.csv` and `backtest_results.xlsx`.
