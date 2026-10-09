"""Pre-trade risk checks and the daily kill switch."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import RiskConfig
from .models import Side
from .portfolio import Portfolio


class RiskManager:
    def __init__(self, cfg: RiskConfig, portfolio: Portfolio):
        self.cfg = cfg
        self.portfolio = portfolio
        self.halted_reason: Optional[str] = None

    def new_day(self) -> None:
        self.halted_reason = None

    def halt(self, reason: str) -> None:
        if self.halted_reason is None:
            self.halted_reason = reason

    def check_daily_loss(self, prices: dict[str, float]) -> bool:
        """Trip the kill switch when realised + unrealised P&L breaches the limit."""
        pnl = self.portfolio.day_realized() + self.portfolio.unrealized(prices)
        if pnl <= -abs(self.cfg.max_daily_loss):
            self.halt(f"daily loss limit hit (pnl={pnl:.2f})")
        return self.halted_reason is not None

    def check_entry(
        self, strategy: str, symbol: str, side: Side, qty: int, price: float, now: datetime
    ) -> Optional[str]:
        """Return a rejection reason, or None if the new-risk order is allowed.

        Exits/reductions must NOT go through this: they are always allowed.
        """
        c = self.cfg
        if self.halted_reason:
            return f"halted: {self.halted_reason}"
        if not (c.entry_start <= now.time() < c.entry_end):
            return f"outside entry window {c.entry_start}-{c.entry_end}"
        if qty <= 0:
            return "quantity must be positive"
        if qty > c.max_order_qty:
            return f"qty {qty} > max_order_qty {c.max_order_qty}"
        value = qty * price
        if value > c.max_order_value:
            return f"order value {value:.0f} > max_order_value {c.max_order_value:.0f}"
        if self.portfolio.qty(strategy, symbol) == 0 and self.portfolio.open_count() >= c.max_open_positions:
            return f"max_open_positions {c.max_open_positions} reached"
        if self.portfolio.exposure(strategy) + value > c.max_strategy_capital:
            return f"strategy capital limit {c.max_strategy_capital:.0f} exceeded"
        return None
