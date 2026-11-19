"""PIPELINE TEST ONLY: fake 'option candles' from the Black-Scholes model, shaped like Breeze data.
Never used for real results (run_real.py labels its output MOCK when this is used)."""
import numpy as np
import pandas as pd

from bt import common as C


def model_leg(spot):
    d = C.daily(spot)

    def src(day, expiry, strike, right):
        m = spot[spot.index.normalize() == pd.Timestamp(day)]
        if not len(m) or day not in d.index:
            return pd.DataFrame()
        kind = "C" if right == "CE" else "P"
        iv = C.iv_for(strike, m.Open.iat[0], d.loc[day, "iv"], kind)
        t = np.array([C.years_to_expiry(x, expiry) for x in m.index])
        out = pd.DataFrame(index=m.index)
        for col in ("Open", "Close"):
            out[col] = [float(C.bs_price(s, strike, tt, iv, kind)) for s, tt in zip(m[col].values, t)]
        out["High"], out["Low"] = out[["Open", "Close"]].max(axis=1), out[["Open", "Close"]].min(axis=1)
        return out
    return src
