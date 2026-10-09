"""Strategy registry. Add a new strategy by subclassing Strategy and using @register."""
from __future__ import annotations

from ..config import StrategyConfig
from .base import Strategy

REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    if not cls.type_name:
        raise ValueError(f"{cls.__name__} must set type_name")
    REGISTRY[cls.type_name] = cls
    return cls


def create_strategy(cfg: StrategyConfig) -> Strategy:
    try:
        cls = REGISTRY[cfg.type]
    except KeyError:
        raise ValueError(f"unknown strategy type {cfg.type!r}; available: {sorted(REGISTRY)}") from None
    return cls(cfg.name, cfg.symbols, cfg.timeframe, cfg.params)


from . import ema_crossover, opening_range_breakout, rsi_reversion  # noqa: E402,F401  (register built-ins)
