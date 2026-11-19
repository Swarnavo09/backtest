"""
Download REAL historical 1-minute NSE data through the ICICI Direct Breeze API (free with an
ICICI Direct account): the NIFTY 50 index (NSE cash) and NIFTY option contracts (NFO),
including EXPIRED weekly contracts.

Credentials are read from environment variables (never hard-code them, never commit them):
    BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN
The session token is valid for one day. Get it by logging in at
    https://api.icicidirect.com/apiuser/login?api_key=<YOUR_API_KEY>
and copying the "apisession" value from the URL you are redirected to.

Everything downloaded is cached under realdata/cache/ so re-runs don't spend API calls
(Breeze limits: about 100 calls per minute and 5,000 per day).
"""
import json
import os
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
PAUSE = 0.7  # seconds between calls (stays under ~100 calls/min)


def _iso(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Breeze:
    def __init__(self):
        from breeze_connect import BreezeConnect  # pip install breeze-connect
        key, secret, token = (os.environ.get(k) for k in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"))
        if not all((key, secret, token)):
            raise SystemExit("Set BREEZE_API_KEY, BREEZE_API_SECRET and BREEZE_SESSION_TOKEN first (see realdata/README.md).")
        self.b = BreezeConnect(api_key=key)
        self.b.generate_session(api_secret=secret, session_token=token)
        self.calls = 0

    def _get(self, **kw):
        for attempt in range(4):
            time.sleep(PAUSE)
            self.calls += 1
            r = self.b.get_historical_data_v2(**kw)
            if isinstance(r, dict) and r.get("Status") == 200:
                return r.get("Success") or []
            err = (r or {}).get("Error") if isinstance(r, dict) else r
            if attempt == 3:
                print(f"   ! Breeze error for {kw}: {err}")
                return []
            time.sleep(2 * (attempt + 1))
        return []

    @staticmethod
    def _frame(rows):
        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "OI"])
        df = pd.DataFrame(rows)
        tcol = "datetime" if "datetime" in df else [c for c in df.columns if "date" in c.lower() and "expiry" not in c.lower()][0]
        out = pd.DataFrame({
            "Open": pd.to_numeric(df["open"]), "High": pd.to_numeric(df["high"]),
            "Low": pd.to_numeric(df["low"]), "Close": pd.to_numeric(df["close"]),
            "Volume": pd.to_numeric(df.get("volume", 0), errors="coerce"),
            "OI": pd.to_numeric(df.get("open_interest", 0), errors="coerce")})
        out.index = pd.to_datetime(df[tcol]).dt.tz_localize(None)
        return out.sort_index()

    # ------------------------------------------------------------------ index (spot)
    def spot_day(self, day):
        """1-minute NIFTY 50 index candles for one session (cached)."""
        path = os.path.join(CACHE, "spot", f"{pd.Timestamp(day):%Y-%m-%d}.csv")
        if os.path.exists(path):
            return pd.read_csv(path, index_col=0, parse_dates=True)
        d = pd.Timestamp(day).normalize()
        rows = self._get(interval="1minute", from_date=_iso(d + pd.Timedelta(hours=9, minutes=15)),
                         to_date=_iso(d + pd.Timedelta(hours=15, minutes=30)), stock_code="NIFTY",
                         exchange_code="NSE", product_type="cash")
        df = self._frame(rows)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path)
        return df

    # ------------------------------------------------------------------ options
    def option_day(self, day, expiry, strike, right):
        """1-minute candles of one NIFTY option contract on one day (cached). right = 'CE' or 'PE'."""
        tag = f"{pd.Timestamp(day):%Y-%m-%d}_{pd.Timestamp(expiry):%Y-%m-%d}_{int(strike)}{right}"
        path = os.path.join(CACHE, "options", f"{tag}.csv")
        if os.path.exists(path):
            return pd.read_csv(path, index_col=0, parse_dates=True)
        d = pd.Timestamp(day).normalize()
        rows = self._get(interval="1minute", from_date=_iso(d + pd.Timedelta(hours=9, minutes=15)),
                         to_date=_iso(d + pd.Timedelta(hours=15, minutes=30)), stock_code="NIFTY",
                         exchange_code="NFO", product_type="options",
                         expiry_date=_iso(pd.Timestamp(expiry).normalize() + pd.Timedelta(hours=7)),
                         right="call" if right == "CE" else "put", strike_price=str(int(strike)))
        df = self._frame(rows)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path)
        return df


def save_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)
