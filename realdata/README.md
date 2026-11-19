# Backtest on REAL NSE prices (ICICI Direct Breeze, free)

This runs the refined strategy (`STRATEGY.md` v2) on **actual traded 1‑minute prices**:
- the NIFTY 50 index from NSE;
- every option leg the strategy trades, including **expired weekly contracts**.

It replaces the Black‑Scholes estimates. Everything runs **on your own PC**, and the Excel is saved to a folder you choose.

## 1. One‑time setup
1. You need an **ICICI Direct trading account**. The Breeze API and its historical data are free for account holders.
2. Go to **https://api.icicidirect.com**, log in, and register an app. Any redirect URL works, for example `http://127.0.0.1`. Note your **API key** and **secret key**.
3. Install the packages:
   ```
   pip install breeze-connect pandas numpy pyarrow openpyxl matplotlib
   ```
4. Get the code:
   ```
   git clone -b claude/tender-faraday-m1mwuz https://github.com/Swarnavo09/backtest.git
   cd backtest
   ```

## 2. Each day you run it: get a session token
- Open `https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY` (URL‑encode the key if it contains special characters) and log in.
- You'll be redirected to a URL containing `apisession=XXXXXXXX`. That value is your session token, valid for one day.

## 3. Run
**Windows (Command Prompt):**
```
set BREEZE_API_KEY=your_api_key
set BREEZE_API_SECRET=your_secret
set BREEZE_SESSION_TOKEN=the_apisession_value
python realdata\run_real.py --out "C:\Users\%USERNAME%\Documents\NiftyBacktest"
```
**macOS / Linux:**
```
export BREEZE_API_KEY=... BREEZE_API_SECRET=... BREEZE_SESSION_TOKEN=...
python realdata/run_real.py --out ~/Documents/NiftyBacktest
```

**What happens:**
- It downloads about 600 days of 1‑minute NIFTY index data plus about 140 option legs, roughly 750 API calls (Breeze allows about 5,000 a day).
- It takes about 10–15 minutes.
- It then writes `nifty_supertrend_backtest_REAL_<from>_<to>.xlsx` into your `--out` folder. The sheets are: Summary, Yearly + best/worst week, every trade (real entry and exit premiums, direction, comment), Weekly P&L, Rules.
- Downloads are cached in `realdata/cache/`. If the API limit or a network error stops the run, re‑run it with a fresh token and it carries on from where it stopped.

**Options:**
- `--spot local`: use the bundled public 1‑minute index file instead of downloading spot. This is faster and uses fewer API calls.
- `--years 1`: test only the last year.

## How real fills are simulated
- **Entry:** at the first real traded price after the signal candle closes.
  - Hedge leg: bought at the open of the next minute + 0.5 pt slippage.
  - Short leg: sold at the open of the next minute − 0.5 pt slippage.
- **Monitoring:** stop, lock, trail, target and the daily cap are checked on **real minute closes**.
- **Exit:** filled at the next minute's real open, with slippage.
- **Illiquid minutes:** these carry the last traded price forward.
- **Missing data:** if a leg has no data that day, the trade is **skipped and listed**, never filled with made‑up prices.
- **Charges:** full Indian F&O charges, as in the rest of the repo.

**Your credentials stay in environment variables on your PC.** Don't paste them into any file you commit or share.
