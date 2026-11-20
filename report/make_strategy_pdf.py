"""Builds report/Nifty_Intraday_Spread_Strategy_Guide.pdf from results/final_mtt.json (plain-English guide)."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
D = json.loads((ROOT / "results" / "final_mtt.json").read_text())
A, B = D["4"], D["6"]          # 4 lots, 6 lots


def inr(n, sign=False):
    n = int(round(n)); neg = n < 0; s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head: parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("−" if neg else ("+" if sign else "")) + "₹" + s


def chart():
    W, H, ml, mr, mt, mb = 700, 230, 70, 14, 12, 28
    ser = {"6 lots": B["equity"], "4 lots": A["equity"]}
    allv = [v for s in ser.values() for _, v in s]; lo, hi = min(0, min(allv)), max(allv)
    n = len(B["equity"])
    X = lambda i, m: ml + (W - ml - mr) * i / (m - 1)
    Y = lambda v: mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo))
    g = []
    step = 200000
    t = 0
    while t <= hi:
        g.append(f'<line x1="{ml}" x2="{W-mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="#e3e6ec"/><text x="{ml-8}" y="{Y(t)+4:.1f}" text-anchor="end" font-size="10" fill="#6b7280">{inr(t)}</text>')
        t += step
    dates = [d for d, _ in B["equity"]]
    for yr in (2022, 2023, 2024, 2025, 2026):
        idx = next((i for i, d in enumerate(dates) if d.startswith(str(yr))), None)
        if idx is not None:
            g.append(f'<text x="{X(idx, n):.1f}" y="{H-8}" font-size="10" fill="#6b7280">{yr}</text>')
    cols = {"6 lots": "#1d4ed8", "4 lots": "#f08a24"}
    for name, s in ser.items():
        m = len(s)
        pts = " ".join(f"{X(i, m):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(s))
        g.append(f'<polyline points="{pts}" fill="none" stroke="{cols[name]}" stroke-width="2"/>')
    leg = f'<rect x="{ml+10}" y="{mt+4}" width="14" height="3" fill="{cols["6 lots"]}"/><text x="{ml+30}" y="{mt+9}" font-size="11">6 lots</text><rect x="{ml+84}" y="{mt+4}" width="14" height="3" fill="{cols["4 lots"]}"/><text x="{ml+104}" y="{mt+9}" font-size="11">4 lots</text>'
    return f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Profit growth over five years">{"".join(g)}{leg}</svg>'


def row(label, a, b, note=""):
    return f"<tr><td>{label}</td><td class='r'>{a}</td><td class='r'>{b}</td><td class='n'>{note}</td></tr>"


yrs = sorted(B["years"])
year_rows = "".join(
    f"<tr><td>{y}{' (to 19 Nov)' if int(y) == 2026 else ''}</td><td class='r'>{B['trades_per_year'][y]}</td><td class='r good'>{inr(A['years'][y], True)}</td><td class='r good'>{inr(B['years'][y], True)}</td></tr>"
    for y in yrs)

html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 16mm 15mm 18mm 15mm; }}
* {{ box-sizing: border-box; }}
body {{ font: 10.5pt/1.5 "Helvetica Neue", Arial, "Segoe UI", sans-serif; color: #1b2230; margin: 0; }}
h1 {{ font-size: 24pt; margin: 0 0 4px; letter-spacing: -.01em; }}
h2 {{ font-size: 14pt; margin: 20px 0 6px; padding-top: 4px; color: #12305f; break-after: avoid; }}
h3 {{ font-size: 11pt; margin: 12px 0 4px; break-after: avoid; }}
p {{ margin: 0 0 7px; }} ul, ol {{ margin: 3px 0 8px; padding-left: 20px; }} li {{ margin-bottom: 3px; }}
.sub {{ color: #4b5565; font-size: 11.5pt; margin-bottom: 12px; }}
.box {{ border: 1px solid #cfd6e4; background: #f5f8fd; border-radius: 8px; padding: 10px 14px; margin: 8px 0 10px; break-inside: avoid; }}
.warn {{ border-color: #e3b867; background: #fff7e6; }}
.ok {{ border-color: #9fd3b0; background: #f0faf3; }}
table {{ border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 9.8pt; break-inside: avoid; }}
th, td {{ padding: 5px 8px; border-bottom: 1px solid #dfe3ec; text-align: left; vertical-align: top; }}
th {{ background: #eef2f9; font-size: 9pt; color: #3a4658; }}
td.r, th.r {{ text-align: right; white-space: nowrap; }} td.n {{ color: #5b6577; font-size: 9pt; }}
.good {{ color: #0b7a3b; }} .bad {{ color: #b3261e; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 8px 0 10px; }}
.kpi {{ border: 1px solid #cfd6e4; border-radius: 8px; padding: 8px 10px; break-inside: avoid; }}
.kpi b {{ display: block; font-size: 15pt; }} .kpi span {{ font-size: 8.5pt; color: #5b6577; }}
.step {{ display: flex; gap: 10px; margin: 6px 0; break-inside: avoid; }}
.step .num {{ flex: none; width: 24px; height: 24px; border-radius: 50%; background: #12305f; color: #fff; text-align: center; font-weight: 700; line-height: 24px; }}
.small {{ font-size: 9pt; color: #5b6577; }}
.pb {{ break-before: page; }}
</style></head><body>

<h1>Nifty Intraday Spread Strategy</h1>
<div class="sub">A plain-English guide · trade Monday, Tuesday and Thursday · every trade closed by 3:00 PM</div>

<h2>1. The idea in one minute</h2>
<p>On each of your trading days you wait for Nifty to show a clear direction. When it does, you place a <b>two-option trade</b>. You <b>sell</b> one option and <b>buy</b> a cheaper one further away as protection. You collect money (a "premium") when you open the trade. If Nifty goes your way or stays quiet, the options lose value during the day and you keep part of that money. If Nifty moves against you, the option you bought stops the loss from becoming huge, and a stop-loss closes the trade early anyway. Everything is closed by 3:00 PM. Nothing is held overnight.</p>
<ul>
<li>If Nifty looks like it is going <b>up</b>: sell a put, buy a cheaper put (called a <i>bull put spread</i>).</li>
<li>If Nifty looks like it is going <b>down</b>: sell a call, buy a cheaper call (called a <i>bear call spread</i>).</li>
</ul>

<h3>The key numbers at a glance (five years of testing, after all costs)</h3>
<table><tr><th></th><th class="r">4 lots (260 qty)</th><th class="r">6 lots (390 qty)</th></tr>
{row("Total profit, Jan 2022 – 19 Nov 2026", f"<b class='good'>{inr(A['total'], True)}</b>", f"<b class='good'>{inr(B['total'], True)}</b>")}
{row("Number of trades", A['trades'], B['trades'], "about 135 a year, roughly 2–3 a week")}
{row("Trades that made money", f"{A['win']}%", f"{B['win']}%", "a little over half")}
{row("Biggest loss on one trade (planned)", f"≈ {inr(-12900)}", f"≈ {inr(-19300)}", "stop-loss plus costs")}
{row("Worst fall from a profit peak", f"<span class='bad'>{inr(A['max_dd'])}</span>", f"<span class='bad'>{inr(B['max_dd'])}</span>", "the toughest stretch in 5 years")}
{row("Profitable months", f"{A['months_up']} of {A['months']}", f"{B['months_up']} of {B['months']}")}
</table>
<p class="small">Every year from 2022 to 2026 ended in profit. These are backtest results, not guaranteed returns. See section 9 for the limits of this test.</p>

<h2>2. Words used in this guide</h2>
<table>
<tr><td><b>Lot</b></td><td>One lot of Nifty options is 65 quantity. 4 lots = 260, 6 lots = 390.</td></tr>
<tr><td><b>ATM</b></td><td>"At the money": the strike nearest to where Nifty is trading now (strikes are 50 apart).</td></tr>
<tr><td><b>OTM 300</b></td><td>A strike 300 points away from ATM, further from the current price. Cheaper than ATM.</td></tr>
<tr><td><b>Premium</b></td><td>The price of an option. Selling an option gives you the premium. Buying costs you the premium.</td></tr>
<tr><td><b>Hedge</b></td><td>The cheaper option you buy to cap your loss.</td></tr>
<tr><td><b>EMA</b></td><td>A smoothed average of recent prices. When a fast EMA (9) is above a slow EMA (21), the trend is up.</td></tr>
<tr><td><b>Supertrend</b></td><td>A line on the chart that sits below the price in an uptrend and above it in a downtrend.</td></tr>
<tr><td><b>Stop-loss</b></td><td>The loss amount at which you close the trade, no matter what.</td></tr>
<tr><td><b>MIS</b></td><td>The intraday order type. Positions are closed the same day.</td></tr>
</table>

<h2>3. The rules, step by step</h2>
<div class="step"><div class="num">1</div><div><b>Pick the days.</b> Trade on <b>Monday, Tuesday and Thursday</b> only. Do nothing on Wednesday and Friday. One trade a day at most.</div></div>
<div class="step"><div class="num">2</div><div><b>Check the bigger direction (30-minute chart).</b><br>EMA 9 above EMA 21 = <b>bullish</b> day. EMA 9 below EMA 21 = <b>bearish</b> day.</div></div>
<div class="step"><div class="num">3</div><div><b>Wait for the entry signal (15-minute chart).</b> A signal needs all of these to be true at the close of a 15-minute candle:
<table style="margin-top:6px"><tr><th>Bullish</th><th>Bearish</th></tr>
<tr><td>Price is above the Supertrend line (settings 10 and 3)</td><td>Price is below the Supertrend line</td></tr>
<tr><td>EMA 9 is above EMA 21</td><td>EMA 9 is below EMA 21</td></tr>
<tr><td>Price is above EMA 21</td><td>Price is below EMA 21</td></tr>
<tr><td>The 30-minute check from step 2 is bullish</td><td>The 30-minute check from step 2 is bearish</td></tr></table>
The signal candle must close between <b>9:30 AM and 1:30 PM</b>. If everything already agrees at 9:30, you enter then. After 1:30 PM, no new trade.</div></div>
<div class="step"><div class="num">4</div><div><b>Place the two orders (buy the protection first).</b>
<table style="margin-top:6px"><tr><th></th><th>Bullish day</th><th>Bearish day</th></tr>
<tr><td>First: BUY the hedge</td><td>Put at ATM − 300</td><td>Call at ATM + 300</td></tr>
<tr><td>Then: SELL</td><td>Put at ATM</td><td>Call at ATM</td></tr></table>
Use the nearest weekly expiry, including on expiry day itself. Same quantity on both: <b>260 for 4 lots, 390 for 6 lots</b>. Use limit orders to keep your fill price close to the quote.</div></div>
<div class="step"><div class="num">5</div><div><b>Close the trade at whichever comes first:</b>
<ul style="margin-top:4px">
<li><b>Loss limit:</b> your total loss reaches <b>₹3,000 per lot</b> (₹12,000 for 4 lots, ₹18,000 for 6 lots). Close both options.</li>
<li><b>Trend turns:</b> the 30-minute EMA 9 crosses to the other side of EMA 21 (the day's direction flips). Close both options.</li>
<li><b>Time:</b> <b>3:00 PM</b>. Close both options.</li></ul>
When closing, buy back the option you sold first, then sell the protection.</div></div>
<div class="box"><b>What you do not use:</b> no profit target and no trailing stop. Both were tested and added nothing, because most winning trades are still gaining at 3:00 PM.</div>

<h3>A worked example (made-up numbers to show how it works)</h3>
<p>It is a Tuesday at 10:15 AM, Nifty is at 25,230, the 30-minute trend is up and every 15-minute condition is met, so ATM is 25,250. You buy the 24,950 put at ₹20 and sell the 25,250 put at ₹105. You collect <b>85 points</b>, which is about <b>₹33,150</b> at 6 lots. If Nifty stays above 25,250 and the options decay, you might buy the spread back at about 40 by 3:00 PM and keep roughly 45 points, about ₹17,500. If Nifty falls and your loss reaches ₹18,000, you close the trade there. The most you could ever lose on this trade, even if the stop failed, is the 300-point gap minus the 85 points collected: <b>215 points, about ₹84,000</b>. That is the hedge doing its job.</p>

<h2>4. Maximum profit and maximum loss</h2>
<table><tr><th></th><th class="r">4 lots</th><th class="r">6 lots</th><th>What it means</th></tr>
{row("Most you can make on one trade", "≈ ₹22,000", "≈ ₹33,000", "capped at the premium you collect (about 85 points on an average day)")}
{row("Best trade in 5 years", f"<span class='good'>{inr(A['best_trade'], True)}</span>", f"<span class='good'>{inr(B['best_trade'], True)}</span>", "a day with unusually high premiums")}
{row("Average winning trade", inr(A['avg_win'], True), inr(B['avg_win'], True))}
{row("Average losing trade", f"<span class='bad'>{inr(A['avg_loss'])}</span>", f"<span class='bad'>{inr(B['avg_loss'])}</span>")}
{row("Planned maximum loss on one trade", "≈ −₹12,900", "≈ −₹19,300", "the ₹3,000-per-lot stop plus brokerage, taxes and slippage")}
{row("Worst single trade in 5 years", f"<span class='bad'>{inr(A['worst_trade'])}</span>", f"<span class='bad'>{inr(B['worst_trade'])}</span>", "stayed close to the stop level in the test")}
{row("Absolute worst case on one trade", "≈ −₹56,000", "≈ −₹84,000", "only if the stop fails, for example in a huge gap; the hedge then caps the loss")}
{row("Most losing trades in a row", f"{A['max_loss_streak']}", f"{B['max_loss_streak']}", "the longest run in 5 years")}
{row("Worst month", f"<span class='bad'>{inr(A['worst_month'][1])}</span>", f"<span class='bad'>{inr(B['worst_month'][1])}</span>", "March 2022")}
{row("Best month", f"<span class='good'>{inr(A['best_month'][1], True)}</span>", f"<span class='good'>{inr(B['best_month'][1], True)}</span>", "November 2026 (still running)")}
{row("Worst fall from a profit peak", f"<span class='bad'>{inr(A['max_dd'])}</span>", f"<span class='bad'>{inr(B['max_dd'])}</span>", "plan for a fall this big, and likely bigger one day")}
</table>
<div class="box warn"><b>Plan for losses bigger than any in the table.</b> The worst stretch in the past is not the worst that can ever happen. Only risk money you can afford to lose.</div>

<h2>5. How it did, year by year</h2>
<table><tr><th>Year</th><th class="r">Trades</th><th class="r">Profit, 4 lots</th><th class="r">Profit, 6 lots</th></tr>{year_rows}</table>
{chart()}
<p class="small">Growth of total profit over time after all costs. Short pauses and dips are normal.</p>

<h2>6. Important: which days really make the money</h2>
<p>In the past, <b>expiry day</b> (the last day of a weekly option contract) has been where most of the profit comes from, because options lose value fastest that day. NSE moved the Nifty weekly expiry from <b>Thursday to Tuesday</b> in September 2025. The table shows what that did to each day (6 lots):</p>
<table><tr><th>Day</th><th class="r">Until Aug 2025<br>(Thursday was expiry)</th><th class="r">Sep 2025 onward<br>(Tuesday is expiry)</th></tr>
<tr><td>Monday</td><td class="r bad">{inr(-8719)}</td><td class="r good">{inr(158819, True)}</td></tr>
<tr><td>Tuesday</td><td class="r bad">{inr(-73988)}</td><td class="r good">{inr(390073, True)}</td></tr>
<tr><td>Thursday</td><td class="r good">{inr(727581, True)}</td><td class="r">{inr(3374, True)}</td></tr>
<tr><td><b>All three together</b></td><td class="r good"><b>{inr(644874, True)}</b></td><td class="r good"><b>{inr(552266, True)}</b></td></tr></table>
<div class="box warn"><b>What this means for you.</b> Thursday made about ₹7.3 lakh of the 6-lot profit, but nearly all of it came while Thursday was expiry day. Since September 2025, Thursday has roughly broken even and <b>Tuesday (now expiry day) and Monday (the day before) are earning the profit</b>. Mon + Tue + Thu still made money in both periods, so it is a reasonable plan. Going forward, expect Tuesday to do most of the work, and treat Thursday as a quiet day that neither helps nor hurts much. A version trading only Monday and Tuesday made +₹4.66 lakh at 6 lots over the full period, but lost money until August 2025, so it has less history behind it.</div>

<h2>7. Money you need</h2>
<table><tr><th></th><th class="r">4 lots</th><th class="r">6 lots</th></tr>
<tr><td>Margin blocked on a normal day (approx.)</td><td class="r">≈ ₹2.1 lakh</td><td class="r">≈ ₹3.1 lakh</td></tr>
<tr><td>Margin blocked on expiry day (approx.)</td><td class="r">≈ ₹3.4 lakh</td><td class="r">≈ ₹5.1 lakh</td></tr>
<tr><td>Cushion for a bad stretch (the worst fall so far)</td><td class="r">≈ ₹1.1 lakh</td><td class="r">≈ ₹1.6 lakh</td></tr>
<tr><td><b>Comfortable account size</b></td><td class="r"><b>₹4.5 – 5 lakh</b></td><td class="r"><b>₹6.5 – 7 lakh</b></td></tr></table>
<p class="small">SEBI adds extra margin on options that expire the same day, so expiry day needs more. Margin figures are estimates. Check your broker's margin calculator before trading.</p>

<h2>8. Settings to enter in AlgoRooms</h2>
<table>
<tr><td><b>Strategy type</b></td><td>Option Trading – Indicator Based, Spot, NIFTY 50</td></tr>
<tr><td><b>Order type / chart</b></td><td>MIS, Candle chart, <b>15 min</b> interval</td></tr>
<tr><td><b>Days</b></td><td><b>MON, TUE, THU</b> only</td></tr>
<tr><td><b>Start time / Square off</b></td><td>09:30 AM / <b>03:00 PM</b></td></tr>
<tr><td><b>Leg 1</b></td><td>BUY · Long = PE, Short = CE · WEEKLY · Strike type <b>OTM 300</b> · Qty 260 or 390</td></tr>
<tr><td><b>Leg 2</b></td><td>SELL · Long = PE, Short = CE · WEEKLY · Strike <b>ATM</b> · same Qty</td></tr>
<tr><td><b>Long entry</b> (all joined with AND)</td><td>Close &gt; SuperTrend(10, 3) · EMA(9) &gt; EMA(21) · Close &gt; EMA(21) · EMA(9, interval 30) &gt; EMA(21, interval 30)</td></tr>
<tr><td><b>Short entry</b></td><td>The same four conditions with "Less than"</td></tr>
<tr><td><b>Exit conditions (tick)</b></td><td>Long exit: EMA(9, interval 30) &lt; EMA(21, interval 30). Short exit: EMA(9, interval 30) &gt; EMA(21, interval 30)</td></tr>
<tr><td><b>Risk management</b></td><td>Exit When Over All Loss: <b>₹12,000</b> (4 lots) or <b>₹18,000</b> (6 lots) · profit target empty · No Trailing · Max Trade Cycle 1 · No Trade After 01:30 PM</td></tr>
</table>

<h2>9. Limits and honest warnings</h2>
<ul>
<li><b>Option prices in the test are partly modelled.</b> Each option starts from its real closing price on NSE, but prices during the day were calculated from that, not recorded tick by tick. Real results can differ.</li>
<li><b>The test assumes decent fills.</b> It allows ½ point of slippage on every order. Use limit orders. If your average slippage is above about 1 point, the profit mostly disappears.</li>
<li><b>It rests on a small number of strong periods.</b> 2026 alone made about ₹3.2 lakh (4 lots) of the ₹7.8 lakh five-year total. A quieter market can mean a few flat years.</li>
<li><b>Expiry-day dependence.</b> If NSE changes the expiry day again, re-check which days work.</li>
<li><b>The stop can slip.</b> In a fast market or a gap, your exit can be worse than the planned loss. The hedge limits the damage but it is not zero.</li>
<li><b>Lot size and margin rules change.</b> The test uses today's lot size of 65 for all years.</li>
<li>SEBI's own study found that about 9 in 10 individual F&amp;O traders lost money over FY22–FY24. This guide is a record of a backtest. It is <b>not investment advice</b>.</li>
</ul>

<h3>Checklist before you start</h3>
<ul>
<li>Run AlgoRooms' own backtest and check you see about 2–3 trades a week.</li>
<li>Paper-trade (or trade 1 lot) for 4–8 weeks and check your real fills against the quote.</li>
<li>Check the Leg 2 strike says <b>OTM 300</b>, not "ATM + 300", so it flips sides correctly on bearish days.</li>
<li>Confirm the margin on expiry day before you place the first trade at full size.</li>
<li>Keep the loss limit in place every single day, with no exceptions.</li>
</ul>
<p class="small">Backtest period: 3 January 2022 to 19 November 2026 on Nifty 15-minute data. Settings were chosen using 2022–2024 and confirmed on 2025–2026. Costs include brokerage, STT, exchange fees, GST, stamp duty and slippage.</p>
</body></html>"""

(ROOT / "report" / "strategy_guide.html").write_text(html)
print("html written", len(html)//1024, "KB")
