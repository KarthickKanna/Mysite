from __future__ import annotations

from datetime import date, datetime, timedelta

from ..models import Candle, Signal
from . import register
from .base import Strategy


@register
class OpeningRangeBreakout(Strategy):
    """Intraday breakout of the first `range_minutes` high/low; one trade per symbol per day.

    Stop is the opposite side of the range; target is `target_r` x the initial risk.
    The engine's square-off flattens anything still open at the end of the day.
    """

    type_name = "opening_range_breakout"
    defaults = {"range_minutes": 15, "quantity": 1, "target_r": 2.0, "allow_short": True, "market_open": "09:15"}

    def validate(self) -> None:
        h, m = self.p.market_open.split(":")
        self._open = (int(h), int(m))
        if self.p.range_minutes % self.timeframe:
            raise ValueError("range_minutes must be a multiple of the timeframe")
        self._day: dict[str, date] = {}
        self._range: dict[str, list[float]] = {}   # symbol -> [high, low]
        self._done: set[str] = set()              # symbols already traded today
        self._target: dict[str, float] = {}

    def _reset_if_new_day(self, sym: str, d: date) -> None:
        if self._day.get(sym) != d:
            self._day[sym] = d
            self._range.pop(sym, None)
            self._done.discard(sym)
            self._target.pop(sym, None)

    def on_candle(self, candle: Candle, history) -> list[Signal]:
        sym, ts = candle.symbol, candle.ts
        self._reset_if_new_day(sym, ts.date())
        start = datetime.combine(ts.date(), datetime.min.time(), tzinfo=ts.tzinfo).replace(
            hour=self._open[0], minute=self._open[1])
        range_end = start + timedelta(minutes=self.p.range_minutes)

        if ts < range_end:  # still building the opening range
            if ts >= start:
                hi_lo = self._range.setdefault(sym, [candle.high, candle.low])
                hi_lo[0], hi_lo[1] = max(hi_lo[0], candle.high), min(hi_lo[1], candle.low)
            return []

        rng = self._range.get(sym)
        if rng is None:
            return []
        hi, lo = rng
        pos = self.position(sym)

        if pos != 0:  # manage target; the stop is enforced by the engine
            tgt = self._target.get(sym)
            if tgt is not None and ((pos > 0 and candle.close >= tgt) or (pos < 0 and candle.close <= tgt)):
                return [Signal.close(sym, "target hit")]
            return []

        if sym in self._done:
            return []
        if candle.close > hi:
            self._done.add(sym)
            self._target[sym] = candle.close + self.p.target_r * (candle.close - lo)
            return [Signal.buy(sym, self.p.quantity, lo, f"breakout above {hi:.2f}")]
        if candle.close < lo and self.p.allow_short:
            self._done.add(sym)
            self._target[sym] = candle.close - self.p.target_r * (hi - candle.close)
            return [Signal.sell(sym, self.p.quantity, hi, f"breakdown below {lo:.2f}")]
        return []
