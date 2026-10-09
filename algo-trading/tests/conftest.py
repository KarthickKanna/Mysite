import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algotrader.models import Candle  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def synthetic_candles(symbol, days=5, tf=5, start_price=100.0, seed=1, drift=0.0, vol=0.002):
    """Random-walk intraday candles 09:15-15:30 on weekdays starting 2025-01-06 (Monday)."""
    rng = random.Random(seed)
    out, px = [], start_price
    day = datetime(2025, 1, 6, tzinfo=IST)
    for _ in range(days):
        t = day.replace(hour=9, minute=15)
        while t < day.replace(hour=15, minute=30):
            o = px
            c = o * (1 + drift + rng.gauss(0, vol))
            h, l = max(o, c) * (1 + abs(rng.gauss(0, vol / 3))), min(o, c) * (1 - abs(rng.gauss(0, vol / 3)))
            out.append(Candle(symbol, t, round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1000))
            px, t = c, t + timedelta(minutes=tf)
        day += timedelta(days=1)
    return out
