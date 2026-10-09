from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, ClassVar, Sequence

from ..models import Candle, Signal
from ..portfolio import Portfolio


class StrategyContext:
    """Read-only view of engine state handed to a strategy."""

    def __init__(self, name: str, portfolio: Portfolio, clock: Callable[[], datetime]):
        self._name, self._portfolio, self._clock = name, portfolio, clock

    def position(self, symbol: str) -> int:
        """This strategy's own signed position (+long / -short) in `symbol`."""
        return self._portfolio.qty(self._name, symbol)

    @property
    def now(self) -> datetime:
        return self._clock()


class Strategy(ABC):
    """Base class for all strategies.

    Subclass, set `type_name` and `defaults`, implement `on_candle`, and decorate with
    `@register` (see strategies/__init__.py). Parameters come from the YAML config and
    are available as `self.p.<name>`; unknown parameter names are rejected.

    `on_candle` is called once per CLOSED candle of `self.timeframe` minutes for each of
    `self.symbols`. `history` includes the candle just closed (oldest first). Return a
    list of Signals; the engine applies risk checks, routes orders and tracks P&L.
    Strategies must be pure functions of (history, own state, ctx) so the same code runs
    in live, paper and backtest.
    """

    type_name: ClassVar[str] = ""
    defaults: ClassVar[dict[str, Any]] = {}

    def __init__(self, name: str, symbols: list[str], timeframe: int, params: dict[str, Any] | None = None):
        params = params or {}
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"{self.type_name}: unknown params {sorted(unknown)}; valid: {sorted(self.defaults)}")
        self.name = name
        self.symbols = symbols
        self.timeframe = timeframe
        self.p = SimpleNamespace(**{**self.defaults, **params})
        self.ctx: StrategyContext | None = None  # set by the engine
        self.validate()

    def validate(self) -> None:
        """Override to sanity-check self.p; raise ValueError on bad config."""

    @property
    def min_history(self) -> int:
        """Candles needed before signals are meaningful (used for live warm-up)."""
        return 0

    def position(self, symbol: str) -> int:
        return self.ctx.position(symbol) if self.ctx else 0

    @abstractmethod
    def on_candle(self, candle: Candle, history: Sequence[Candle]) -> list[Signal]:
        ...
