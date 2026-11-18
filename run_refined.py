"""Refined (v2) strategy: same as run_final.py but Supertrend(10, 2.0) and ADX(14) > 30 (tuned on 2019-2024 only).
Writes results/refined/."""
import os
import run_final as R

R.FINAL = dict(R.FINAL, st_period=10, st_mult=2.0, adx_period=14, adx_min=30)
R.OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "refined")

if __name__ == "__main__":
    R.main()
