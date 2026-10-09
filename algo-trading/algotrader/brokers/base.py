from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OrderRequest, OrderResult


class Broker(ABC):
    """Order execution interface. The engine only ever talks to this."""

    @abstractmethod
    def place_order(self, req: OrderRequest) -> OrderResult:
        """Place a MARKET order and (best effort) wait for the fill."""

    def update_price(self, symbol: str, price: float) -> None:
        """Hook for brokers that simulate fills (paper)."""
