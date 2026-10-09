"""Plain data types shared across the framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    ts: datetime
    cum_volume: Optional[int] = None  # day-cumulative traded volume, if the feed has it


@dataclass(frozen=True)
class Candle:
    symbol: str
    ts: datetime  # candle START time
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass
class Signal:
    """What a strategy asks the engine to do.

    Use `Signal.close(symbol)` to flatten the strategy's own position in a symbol.
    `stop_loss` is an absolute price; the engine enforces it on every tick.
    """

    symbol: str
    side: Optional[Side] = None
    quantity: int = 0
    stop_loss: Optional[float] = None
    close_position: bool = False
    reason: str = ""
    strategy: str = ""  # filled in by the engine

    @classmethod
    def buy(cls, symbol: str, quantity: int, stop_loss: float | None = None, reason: str = "") -> "Signal":
        return cls(symbol, Side.BUY, quantity, stop_loss, reason=reason)

    @classmethod
    def sell(cls, symbol: str, quantity: int, stop_loss: float | None = None, reason: str = "") -> "Signal":
        return cls(symbol, Side.SELL, quantity, stop_loss, reason=reason)

    @classmethod
    def close(cls, symbol: str, reason: str = "") -> "Signal":
        return cls(symbol, close_position=True, reason=reason)


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    tag: str = ""
    ref_price: float = 0.0  # last known price; used by the paper broker and for logging


@dataclass
class OrderResult:
    order_id: str
    status: str  # COMPLETE | REJECTED | PENDING
    filled_qty: int = 0
    avg_price: float = 0.0
    message: str = ""

    @property
    def filled(self) -> bool:
        return self.status == "COMPLETE" and self.filled_qty > 0


@dataclass
class Position:
    """One strategy's net position in one symbol."""

    qty: int = 0  # signed: +long, -short
    avg_price: float = 0.0
    stop_loss: Optional[float] = None
    opened_at: Optional[datetime] = None
    meta: dict = field(default_factory=dict)
