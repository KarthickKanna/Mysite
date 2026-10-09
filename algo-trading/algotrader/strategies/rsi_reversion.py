from __future__ import annotations

from ..indicators import rsi
from ..models import Candle, Signal
from . import register
from .base import Strategy


@register
class RsiReversion(Strategy):
    """Mean reversion (long only): buy oversold RSI, exit when RSI recovers."""

    type_name = "rsi_reversion"
    defaults = {"period": 14, "oversold": 30, "exit_level": 55, "quantity": 1, "stop_loss_pct": 0.015}

    @property
    def min_history(self) -> int:
        return self.p.period + 1

    def on_candle(self, candle: Candle, history) -> list[Signal]:
        value = rsi([c.close for c in history], self.p.period)
        if value is None:
            return []
        pos = self.position(candle.symbol)
        if pos == 0 and value < self.p.oversold:
            return [Signal.buy(candle.symbol, self.p.quantity, candle.close * (1 - self.p.stop_loss_pct),
                               f"rsi {value:.1f} < {self.p.oversold}")]
        if pos > 0 and value > self.p.exit_level:
            return [Signal.close(candle.symbol, f"rsi {value:.1f} > {self.p.exit_level}")]
        return []
