from __future__ import annotations

import itertools

from ..models import OrderRequest, OrderResult
from .base import Broker


class PaperBroker(Broker):
    """Simulated broker: fills market orders instantly at the last price (+ optional slippage)."""

    def __init__(self, slippage_pct: float = 0.0):
        self.slippage_pct = slippage_pct
        self._prices: dict[str, float] = {}
        self._ids = itertools.count(1)

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def place_order(self, req: OrderRequest) -> OrderResult:
        oid = f"PAPER-{next(self._ids)}"
        px = req.ref_price or self._prices.get(req.symbol)
        if not px:
            return OrderResult(oid, "REJECTED", message=f"no price for {req.symbol}")
        px *= 1 + req.side.sign * self.slippage_pct
        return OrderResult(oid, "COMPLETE", req.quantity, round(px, 2))
