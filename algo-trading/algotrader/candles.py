"""Turns a stream of ticks into fixed-timeframe candles."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .models import Candle, Tick


def bucket_start(ts: datetime, minutes: int) -> datetime:
    """Start of the `minutes`-wide bucket containing ts, aligned to midnight.

    Matches Kite's 1/3/5/10/15/30-minute candles for NSE (09:15 open). It does NOT match
    Kite's 60-minute candles (which start at 09:15, 10:15, ...).
    """
    midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((ts - midnight).total_seconds() // 60)
    return midnight + timedelta(minutes=elapsed - elapsed % minutes)


class CandleAggregator:
    """Per-symbol tick -> candle builder. `on_tick` returns a candle when one closes."""

    def __init__(self, symbol: str, minutes: int):
        self.symbol = symbol
        self.minutes = minutes
        self._start: Optional[datetime] = None
        self._o = self._h = self._l = self._c = 0.0
        self._vol = 0
        self._last_cum: Optional[int] = None

    def on_tick(self, tick: Tick) -> Optional[Candle]:
        start = bucket_start(tick.ts, self.minutes)
        closed = None
        if self._start is not None and start > self._start:
            closed = self._snapshot()
            self._start = None
        if self._start is None:
            self._start = start
            self._o = self._h = self._l = self._c = tick.price
            self._vol = 0
        else:
            self._h = max(self._h, tick.price)
            self._l = min(self._l, tick.price)
            self._c = tick.price
        if tick.cum_volume is not None:
            if self._last_cum is not None and tick.cum_volume >= self._last_cum:
                self._vol += tick.cum_volume - self._last_cum
            self._last_cum = tick.cum_volume
        return closed

    def flush(self) -> Optional[Candle]:
        """Force-close the in-progress candle (end of day)."""
        if self._start is None:
            return None
        c = self._snapshot()
        self._start = None
        return c

    def _snapshot(self) -> Candle:
        return Candle(self.symbol, self._start, self._o, self._h, self._l, self._c, self._vol)
