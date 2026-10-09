"""Tracks each strategy's positions and realised P&L, independent of the broker's netted view."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterator, Optional

from .models import Position, Side


class Portfolio:
    def __init__(self) -> None:
        self._pos: dict[tuple[str, str], Position] = {}
        self.realized: dict[str, float] = defaultdict(float)  # per strategy
        self.fees: float = 0.0
        self._day_base: float = 0.0  # total_realized() at the start of the current trading day

    # ---- queries ----
    def position(self, strategy: str, symbol: str) -> Position:
        return self._pos.get((strategy, symbol)) or Position()

    def qty(self, strategy: str, symbol: str) -> int:
        return self.position(strategy, symbol).qty

    def open_positions(self) -> Iterator[tuple[str, str, Position]]:
        for (strat, sym), p in list(self._pos.items()):
            if p.qty != 0:
                yield strat, sym, p

    def open_count(self, strategy: Optional[str] = None) -> int:
        return sum(1 for s, _, _ in self.open_positions() if strategy in (None, s))

    def exposure(self, strategy: Optional[str] = None) -> float:
        """Gross notional at cost."""
        return sum(abs(p.qty) * p.avg_price for s, _, p in self.open_positions() if strategy in (None, s))

    def total_realized(self) -> float:
        return sum(self.realized.values()) - self.fees

    def start_day(self) -> None:
        self._day_base = self.total_realized()

    def day_realized(self) -> float:
        return self.total_realized() - self._day_base

    def unrealized(self, prices: dict[str, float]) -> float:
        return sum((prices.get(sym, p.avg_price) - p.avg_price) * p.qty for _, sym, p in self.open_positions())

    # ---- updates ----
    def apply_fill(
        self,
        strategy: str,
        symbol: str,
        side: Side,
        qty: int,
        price: float,
        ts: datetime,
        stop_loss: Optional[float] = None,
        fee: float = 0.0,
    ) -> float:
        """Apply a fill and return the realised P&L it produced (before fees)."""
        pos = self._pos.setdefault((strategy, symbol), Position())
        signed = side.sign * qty
        realized = 0.0
        self.fees += fee
        if pos.qty == 0 or (pos.qty > 0) == (signed > 0):  # opening / adding
            new_qty = pos.qty + signed
            pos.avg_price = (abs(pos.qty) * pos.avg_price + qty * price) / abs(new_qty)
            if pos.qty == 0:
                pos.opened_at = ts
            pos.qty = new_qty
            if stop_loss is not None:
                pos.stop_loss = stop_loss
        else:  # reducing / closing / flipping
            closing = min(qty, abs(pos.qty))
            realized = (price - pos.avg_price) * closing * (1 if pos.qty > 0 else -1)
            pos.qty += signed
            if pos.qty == 0:
                pos.avg_price, pos.stop_loss, pos.opened_at = 0.0, None, None
            elif (pos.qty > 0) == (signed > 0):  # flipped: remainder is a new position
                pos.avg_price, pos.opened_at = price, ts
                pos.stop_loss = stop_loss
        self.realized[strategy] += realized
        return realized
