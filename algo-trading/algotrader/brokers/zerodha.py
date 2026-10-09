from __future__ import annotations

import logging
import re
import time

from kiteconnect import KiteConnect

from ..models import OrderRequest, OrderResult, Side
from .base import Broker

log = logging.getLogger(__name__)


class ZerodhaBroker(Broker):
    """Live execution through Kite Connect. Sends MARKET orders and polls for the fill."""

    def __init__(self, kite: KiteConnect, exchange: str = "NSE", product: str = "MIS", fill_timeout: float = 5.0):
        self.kite = kite
        self.exchange = exchange
        self.product = product
        self.fill_timeout = fill_timeout

    def place_order(self, req: OrderRequest) -> OrderResult:
        try:
            oid = self.kite.place_order(
                variety=KiteConnect.VARIETY_REGULAR,
                exchange=self.exchange,
                tradingsymbol=req.symbol,
                transaction_type=KiteConnect.TRANSACTION_TYPE_BUY if req.side is Side.BUY else KiteConnect.TRANSACTION_TYPE_SELL,
                quantity=req.quantity,
                product=self.product,
                order_type=KiteConnect.ORDER_TYPE_MARKET,
                tag=re.sub(r"[^A-Za-z0-9]", "", req.tag)[:20] or None,  # Kite: alphanumeric, max 20
            )
        except Exception as e:  # network / validation / margin errors from Kite
            log.exception("place_order failed")
            return OrderResult("", "REJECTED", message=str(e))
        return self._await_fill(str(oid), req.quantity)

    def _await_fill(self, oid: str, qty: int) -> OrderResult:
        deadline = time.monotonic() + self.fill_timeout
        last = None
        while True:
            try:
                history = self.kite.order_history(oid)
                last = history[-1] if history else None
            except Exception:
                log.exception("order_history failed for %s", oid)
            if last:
                status = last["status"]
                if status == "COMPLETE":
                    return OrderResult(oid, "COMPLETE", int(last["filled_quantity"]), float(last["average_price"]))
                if status in ("REJECTED", "CANCELLED"):
                    return OrderResult(oid, "REJECTED", message=last.get("status_message") or status)
            if time.monotonic() >= deadline:
                log.error("order %s not filled within %.0fs (last status=%s)", oid, self.fill_timeout, last and last["status"])
                return OrderResult(oid, "PENDING", message="fill not confirmed; check Kite orderbook")
            time.sleep(0.4)
