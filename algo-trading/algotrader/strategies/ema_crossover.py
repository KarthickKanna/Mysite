from __future__ import annotations

from ..indicators import ema_series
from ..models import Candle, Signal
from . import register
from .base import Strategy


@register
class EmaCrossover(Strategy):
    """Trend following: go long when fast EMA crosses above slow EMA, short on the reverse."""

    type_name = "ema_crossover"
    defaults = {"fast": 9, "slow": 21, "quantity": 1, "stop_loss_pct": 0.01, "allow_short": True}

    def validate(self) -> None:
        if self.p.fast >= self.p.slow:
            raise ValueError("ema_crossover: fast must be < slow")

    @property
    def min_history(self) -> int:
        return self.p.slow + 2

    def on_candle(self, candle: Candle, history) -> list[Signal]:
        closes = [c.close for c in history]
        fast, slow = ema_series(closes, self.p.fast), ema_series(closes, self.p.slow)
        if len(slow) < 2:
            return []
        # align the tails: both series end at the latest candle
        f_prev, f_now, s_prev, s_now = fast[-2], fast[-1], slow[-2], slow[-1]
        pos = self.position(candle.symbol)
        px, sl = candle.close, self.p.stop_loss_pct
        out: list[Signal] = []
        if f_prev <= s_prev and f_now > s_now:
            if pos < 0:
                out.append(Signal.close(candle.symbol, "ema cross up"))
            if pos <= 0:
                out.append(Signal.buy(candle.symbol, self.p.quantity, px * (1 - sl), "ema cross up"))
        elif f_prev >= s_prev and f_now < s_now:
            if pos > 0:
                out.append(Signal.close(candle.symbol, "ema cross down"))
            if pos >= 0 and self.p.allow_short:
                out.append(Signal.sell(candle.symbol, self.p.quantity, px * (1 + sl), "ema cross down"))
        return out
