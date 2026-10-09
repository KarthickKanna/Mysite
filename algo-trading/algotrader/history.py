"""Historical candles: Kite API and CSV."""
from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
INTERVALS = {1: "minute", 3: "3minute", 5: "5minute", 10: "10minute", 15: "15minute", 30: "30minute", 60: "60minute"}
# Kite caps the date span per request by interval; 55 days is safe for every intraday interval.
_CHUNK = timedelta(days=55)


def to_ist(dt: datetime) -> datetime:
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def instrument_tokens(kite, exchange: str, symbols: list[str]) -> dict[str, int]:
    wanted = set(symbols)
    found = {i["tradingsymbol"]: i["instrument_token"] for i in kite.instruments(exchange) if i["tradingsymbol"] in wanted}
    missing = wanted - set(found)
    if missing:
        raise ValueError(f"symbols not found on {exchange}: {sorted(missing)}")
    return found


def fetch_candles(kite, token: int, symbol: str, timeframe: int, start: datetime, end: datetime) -> list[Candle]:
    if timeframe not in INTERVALS:
        raise ValueError(f"timeframe must be one of {sorted(INTERVALS)}")
    out: list[Candle] = []
    cur = start
    while cur < end:
        nxt = min(cur + _CHUNK, end)
        for row in kite.historical_data(token, cur, nxt, INTERVALS[timeframe]):
            out.append(Candle(symbol, to_ist(row["date"]), row["open"], row["high"], row["low"], row["close"],
                              int(row.get("volume", 0))))
        cur = nxt
        time.sleep(0.4)  # historical API: ~3 req/s
    return out


def load_csv(path: str | Path, symbol: str) -> list[Candle]:
    """CSV columns: datetime,open,high,low,close[,volume]; ISO datetimes (naive = IST)."""
    with open(path, newline="") as f:
        return [
            Candle(symbol, to_ist(datetime.fromisoformat(r["datetime"])), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]), int(float(r.get("volume") or 0)))
            for r in csv.DictReader(f)
        ]
