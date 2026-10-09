"""YAML config loading."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any

import yaml


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class RiskConfig:
    max_daily_loss: float = 2000.0          # INR; breaching it halts all trading for the day
    max_order_value: float = 50000.0        # INR per order
    max_order_qty: int = 1000
    max_open_positions: int = 5             # across all strategies
    max_strategy_capital: float = 100000.0  # gross exposure allowed per strategy
    entry_start: time = time(9, 20)
    entry_end: time = time(15, 0)
    square_off: time = time(15, 15)         # flatten everything (MIS is auto-squared by broker ~15:20)


@dataclass
class StrategyConfig:
    name: str
    type: str
    symbols: list[str]
    timeframe: int = 5
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Config:
    exchange: str = "NSE"
    product: str = "MIS"
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategies: list[StrategyConfig] = field(default_factory=list)
    journal_path: str = "logs/trades.jsonl"
    fee_per_order: float = 0.0              # flat brokerage estimate for paper/backtest P&L


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    r = dict(raw.get("risk") or {})
    for k in ("entry_start", "entry_end", "square_off"):
        if k in r:
            r[k] = _t(str(r[k]))
    strategies = [StrategyConfig(**s) for s in raw.get("strategies", [])]
    names = [s.name for s in strategies]
    if len(names) != len(set(names)):
        raise ValueError("strategy names must be unique")
    return Config(
        exchange=raw.get("exchange", "NSE"),
        product=raw.get("product", "MIS"),
        risk=RiskConfig(**r),
        strategies=strategies,
        journal_path=raw.get("journal_path", "logs/trades.jsonl"),
        fee_per_order=float(raw.get("fee_per_order", 0.0)),
    )
