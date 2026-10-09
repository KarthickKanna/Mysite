"""Candle-replay backtester that drives the real Engine with a PaperBroker.

Assumptions (be aware of them before trusting results):
  * signals are generated on a candle's close and filled at that close (+ optional slippage);
  * stop-losses trigger on the candle's low/high (gap fills at the open) -- if one candle
    could touch both stop and target, the stop wins;
  * the broker fee is a flat `fee_per_order`; no taxes/STT/impact modelling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .brokers.paper import PaperBroker
from .config import Config
from .engine import Engine, TradeRecord
from .models import Candle
from .strategies import create_strategy


@dataclass
class Report:
    trades: list[TradeRecord]
    per_strategy: dict[str, dict]
    total_pnl: float
    max_drawdown: float

    def format(self) -> str:
        lines = [f"{'strategy':<22}{'trades':>7}{'win%':>7}{'net pnl':>12}"]
        for name, r in sorted(self.per_strategy.items()):
            lines.append(f"{name:<22}{r['trades']:>7}{r['win_rate']:>7.0%}{r['pnl']:>12.2f}")
        lines.append(f"{'TOTAL':<22}{sum(r['trades'] for r in self.per_strategy.values()):>7}{'':>7}{self.total_pnl:>12.2f}")
        lines.append(f"max drawdown (realised): {self.max_drawdown:.2f}")
        return "\n".join(lines)


def run_backtest(cfg: Config, data: dict[tuple[str, int], list[Candle]], slippage_pct: float = 0.0) -> tuple[Engine, Report]:
    """`data` maps (symbol, timeframe_minutes) -> candles, which must cover what the config's strategies use."""
    strategies = [create_strategy(s) for s in cfg.strategies if s.enabled]
    clock_now: list[datetime] = [datetime.min]
    engine = Engine(cfg, strategies, PaperBroker(slippage_pct), clock=lambda: clock_now[0], write_journal=False)

    events = []
    for (sym, tf) in {(sym, s.timeframe) for s in strategies for sym in s.symbols}:
        if (sym, tf) not in data:
            raise ValueError(f"no data for {sym} @ {tf}m")
        events += [(c.ts + timedelta(minutes=tf), tf, c.symbol, c) for c in data[(sym, tf)]]
    events.sort(key=lambda e: e[:3])  # chronological by candle CLOSE time

    for close_ts, tf, _sym, candle in events:
        clock_now[0] = close_ts
        engine.on_candle(candle, tf)
    engine.square_off_all("end of data")
    return engine, summarize(engine.trades, cfg.fee_per_order)


def summarize(trades: list[TradeRecord], fee: float = 0.0) -> Report:
    per: dict[str, dict] = {}
    equity = peak = max_dd = 0.0
    for t in trades:
        s = per.setdefault(t.strategy, {"trades": 0, "wins": 0, "pnl": 0.0})
        net = t.realized - fee
        s["pnl"] += net
        if t.realized != 0:  # a fill that closed (part of) a position
            s["trades"] += 1
            s["wins"] += net > 0
        equity += net
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    for s in per.values():
        s["win_rate"] = s["wins"] / s["trades"] if s["trades"] else 0.0
    return Report(trades, per, sum(s["pnl"] for s in per.values()), max_dd)
