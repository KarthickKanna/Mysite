"""The engine wires strategies, risk, portfolio and broker together.

Data flow:  ticks -> CandleAggregator -> Strategy.on_candle -> Signal
            -> risk check -> Broker.place_order -> Portfolio -> journal

The same engine runs live, paper and backtest; only the Broker and the source of
candles/ticks differ.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .brokers.base import Broker
from .candles import CandleAggregator
from .config import Config
from .models import Candle, OrderRequest, Side, Signal, Tick
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies.base import Strategy, StrategyContext

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)


def now_ist() -> datetime:
    return datetime.now(IST)


@dataclass
class TradeRecord:
    ts: datetime
    strategy: str
    symbol: str
    side: str
    qty: int
    price: float
    realized: float
    reason: str
    order_id: str


class Engine:
    def __init__(
        self,
        cfg: Config,
        strategies: list[Strategy],
        broker: Broker,
        clock: Callable[[], datetime] = now_ist,
        history_size: int = 500,
        write_journal: bool = True,
    ):
        self.cfg = cfg
        self.strategies = strategies
        self.broker = broker
        self.clock = clock
        self.history_size = history_size
        self.portfolio = Portfolio()
        self.risk = RiskManager(cfg.risk, self.portfolio)
        self.prices: dict[str, float] = {}
        self.trades: list[TradeRecord] = []
        self._journal = Path(cfg.journal_path) if write_journal and cfg.journal_path else None
        self._history: dict[tuple[str, str], list[Candle]] = {}
        self._aggs: dict[tuple[str, int], CandleAggregator] = {}
        self._by_feed: dict[tuple[str, int], list[Strategy]] = {}
        self._day = None
        self._squared_off = False
        self._lock = RLock()
        for s in strategies:
            s.ctx = StrategyContext(s.name, self.portfolio, lambda: self.clock())
            for sym in s.symbols:
                self._by_feed.setdefault((sym, s.timeframe), []).append(s)
                self._history[(s.name, sym)] = []
        self._aggs = {(sym, tf): CandleAggregator(sym, tf) for (sym, tf) in self._by_feed}

    @property
    def feeds(self) -> dict[tuple[str, int], list[Strategy]]:
        """(symbol, timeframe) -> strategies consuming that candle stream."""
        return self._by_feed

    @property
    def symbols(self) -> list[str]:
        return sorted({sym for sym, _ in self._by_feed})

    # ------------------------------------------------------------------ inputs
    def preload(self, symbol: str, timeframe: int, candles: list[Candle]) -> None:
        """Seed indicator history (no signals are generated)."""
        with self._lock:
            for s in self._by_feed.get((symbol, timeframe), []):
                h = self._history[(s.name, symbol)]
                h.extend(candles)
                del h[: -self.history_size]

    def on_tick(self, tick: Tick) -> None:
        with self._lock:
            self.prices[tick.symbol] = tick.price
            self.broker.update_price(tick.symbol, tick.price)
            self.housekeeping()
            self._check_stops(tick.symbol, tick.price, tick.price)
            if self._squared_off or self.risk.halted_reason:
                return
            for (sym, tf), agg in self._aggs.items():
                if sym == tick.symbol:
                    candle = agg.on_tick(tick)
                    if candle:
                        self._on_closed_candle(candle, tf)

    def on_candle(self, candle: Candle, timeframe: int, with_stops: bool = True) -> None:
        """Feed an already-closed candle (backtest / replay). The clock must be set by the caller."""
        with self._lock:
            self.prices[candle.symbol] = candle.close
            self.housekeeping()
            if with_stops:
                self._check_stops(candle.symbol, candle.low, candle.high, candle.open, candle.ts)
            if self._squared_off or self.risk.halted_reason:
                return
            self._on_closed_candle(candle, timeframe)

    # ------------------------------------------------------------ housekeeping
    def housekeeping(self) -> None:
        """Day rollover, scheduled square-off and the daily-loss kill switch. Cheap; call often."""
        with self._lock:
            now = self.clock()
            if self._day != now.date():
                self._day = now.date()
                self._squared_off = False
                self.risk.new_day()
                self.portfolio.start_day()
            if not self._squared_off and now.time() >= self.cfg.risk.square_off:
                self._squared_off = True
                self.square_off_all("scheduled square-off")
            if not self.risk.halted_reason and self.risk.check_daily_loss(self.prices):
                log.error("KILL SWITCH: %s", self.risk.halted_reason)
                self.square_off_all("kill switch")

    def square_off_all(self, reason: str) -> None:
        with self._lock:
            for strat, sym, _ in list(self.portfolio.open_positions()):
                self._close(strat, sym, reason, self.prices.get(sym, 0.0))

    def flush_candles(self) -> None:
        """Process any in-progress candles (e.g. on shutdown)."""
        with self._lock:
            for (sym, tf), agg in self._aggs.items():
                candle = agg.flush()
                if candle:
                    self._on_closed_candle(candle, tf)

    # ---------------------------------------------------------------- internals
    def _on_closed_candle(self, candle: Candle, timeframe: int) -> None:
        for strat in self._by_feed.get((candle.symbol, timeframe), []):
            hist = self._history[(strat.name, candle.symbol)]
            hist.append(candle)
            del hist[: -self.history_size]
            if len(hist) < strat.min_history:
                continue
            try:
                signals = strat.on_candle(candle, list(hist))
            except Exception:
                log.exception("strategy %s crashed on %s; skipping this candle", strat.name, candle)
                continue
            for sig in signals:
                if sig.symbol != candle.symbol:
                    log.warning("%s: ignoring signal for %s (not this candle's symbol)", strat.name, sig.symbol)
                    continue
                sig.strategy = strat.name
                self._handle_signal(sig)

    def _handle_signal(self, sig: Signal) -> None:
        price = self.prices.get(sig.symbol, 0.0)
        pos_qty = self.portfolio.qty(sig.strategy, sig.symbol)
        if sig.close_position:
            self._close(sig.strategy, sig.symbol, sig.reason or "strategy exit", price)
            return
        if sig.side is None:
            log.warning("%s: signal without side/close ignored: %s", sig.strategy, sig)
            return
        if pos_qty != 0 and (pos_qty > 0) != (sig.side is Side.BUY):
            # Opposite to the open position: reduce only. To flip, a strategy emits close() then entry.
            qty = min(sig.quantity, abs(pos_qty))
            self._execute(sig.strategy, sig.symbol, sig.side, qty, price, sig.reason, None)
            return
        if sig.stop_loss is not None and not (
            (sig.side is Side.BUY and sig.stop_loss < price) or (sig.side is Side.SELL and sig.stop_loss > price)
        ):
            log.warning("%s: rejected %s %s: stop_loss %.2f on wrong side of price %.2f",
                        sig.strategy, sig.side.value, sig.symbol, sig.stop_loss, price)
            return
        reason = self.risk.check_entry(sig.strategy, sig.symbol, sig.side, sig.quantity, price, self.clock())
        if reason:
            log.warning("%s: risk rejected %s %d %s: %s", sig.strategy, sig.side.value, sig.quantity, sig.symbol, reason)
            return
        self._execute(sig.strategy, sig.symbol, sig.side, sig.quantity, price, sig.reason, sig.stop_loss)

    def _close(self, strategy: str, symbol: str, reason: str, ref_price: float) -> None:
        qty = self.portfolio.qty(strategy, symbol)
        if qty:
            self._execute(strategy, symbol, Side.SELL if qty > 0 else Side.BUY, abs(qty), ref_price, reason, None)

    def _execute(self, strategy: str, symbol: str, side: Side, qty: int, ref_price: float,
                 reason: str, stop_loss: Optional[float]) -> None:
        res = self.broker.place_order(OrderRequest(symbol, side, qty, tag=strategy, ref_price=ref_price))
        if res.status == "PENDING":
            # Unknown order state => our books may be wrong. Fail safe: stop opening new risk.
            self.risk.halt(f"unconfirmed order {res.order_id} for {strategy}/{symbol}: {res.message}")
            log.error("HALT: %s", self.risk.halted_reason)
            return
        if not res.filled:
            log.warning("%s: order %s %d %s not filled: %s", strategy, side.value, qty, symbol, res.message)
            return
        ts = self.clock()
        realized = self.portfolio.apply_fill(strategy, symbol, side, res.filled_qty, res.avg_price, ts,
                                             stop_loss, self.cfg.fee_per_order)
        self.prices.setdefault(symbol, res.avg_price)
        rec = TradeRecord(ts, strategy, symbol, side.value, res.filled_qty, res.avg_price, realized, reason, res.order_id)
        self.trades.append(rec)
        log.info("FILL %-18s %-4s %4d %-12s @ %9.2f  pnl=%8.2f  (%s)", strategy, side.value, rec.qty, symbol,
                 rec.price, realized, reason)
        if self._journal:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            with self._journal.open("a") as f:
                f.write(json.dumps({**asdict(rec), "ts": ts.isoformat()}) + "\n")

    def _check_stops(self, symbol: str, low: float, high: float, open_: float | None = None,
                     candle_start: datetime | None = None) -> None:
        """Enforce software stop-losses. Tick path: low == high == price. Candle path: use the range."""
        for strat, sym, pos in list(self.portfolio.open_positions()):
            if sym != symbol or pos.stop_loss is None:
                continue
            if candle_start is not None and pos.opened_at is not None and candle_start < pos.opened_at:
                continue  # candle started before we entered; its range is not ours to stop on
            if pos.qty > 0 and low <= pos.stop_loss:
                px = min(pos.stop_loss, open_) if open_ is not None else low  # gap-down fills at the open
            elif pos.qty < 0 and high >= pos.stop_loss:
                px = max(pos.stop_loss, open_) if open_ is not None else high
            else:
                continue
            self._close(strat, sym, "stop-loss", px)
