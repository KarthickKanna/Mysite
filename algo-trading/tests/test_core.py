from datetime import datetime, time, timedelta

import pytest

from algotrader.brokers.paper import PaperBroker
from algotrader.candles import CandleAggregator, bucket_start
from algotrader.config import Config, RiskConfig, StrategyConfig, load_config
from algotrader.engine import Engine
from algotrader.indicators import ema_series, rsi
from algotrader.models import Candle, Side, Signal, Tick
from algotrader.portfolio import Portfolio
from algotrader.strategies import create_strategy
from algotrader.strategies.base import Strategy
from tests.conftest import IST


def at(h, m, s=0, day=6):
    return datetime(2025, 1, day, h, m, s, tzinfo=IST)


# ---------------------------------------------------------------- indicators
def test_ema_and_rsi_known_values():
    assert ema_series([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]
    assert ema_series([1, 2], 3) == []
    assert rsi(list(range(1, 20)), 14) == 100.0           # only gains
    assert rsi([10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0.5, 0.4, 0.3, 0.2, 0.1], 14) < 1
    assert rsi([1, 2, 3], 14) is None


# ---------------------------------------------------------------- candles
def test_bucket_alignment():
    assert bucket_start(at(9, 17), 5) == at(9, 15)
    assert bucket_start(at(9, 44, 59), 15) == at(9, 30)


def test_aggregator_builds_ohlcv_and_closes_on_next_bucket():
    agg = CandleAggregator("X", 5)
    assert agg.on_tick(Tick("X", 100, at(9, 15, 1), 1000)) is None
    assert agg.on_tick(Tick("X", 103, at(9, 16), 1050)) is None
    assert agg.on_tick(Tick("X", 99, at(9, 18), 1080)) is None
    c = agg.on_tick(Tick("X", 101, at(9, 20, 0), 1100))
    assert (c.ts, c.open, c.high, c.low, c.close) == (at(9, 15), 100, 103, 99, 99)
    assert c.volume == 80  # 1080 - 1000; the first tick's cumulative volume is only a baseline


# ---------------------------------------------------------------- portfolio
def test_portfolio_long_short_and_flip():
    p = Portfolio()
    assert p.apply_fill("s", "X", Side.BUY, 10, 100, at(10, 0)) == 0
    assert p.apply_fill("s", "X", Side.BUY, 10, 110, at(10, 1)) == 0
    assert p.position("s", "X").avg_price == 105
    assert p.apply_fill("s", "X", Side.SELL, 5, 115, at(10, 2)) == 50      # (115-105)*5
    assert p.qty("s", "X") == 15
    assert p.apply_fill("s", "X", Side.SELL, 15, 100, at(10, 3)) == -75
    assert p.qty("s", "X") == 0
    assert p.apply_fill("s", "Y", Side.SELL, 10, 50, at(10, 4)) == 0       # short
    assert p.apply_fill("s", "Y", Side.BUY, 10, 40, at(10, 5)) == 100      # profit on short
    assert p.realized["s"] == 50 - 75 + 100


# ---------------------------------------------------------------- config / registry
def test_config_loads_example_and_rejects_bad_params(tmp_path):
    cfg = load_config("config.example.yaml")
    assert cfg.risk.square_off == time(15, 15)
    assert len(cfg.strategies) == 3
    with pytest.raises(ValueError, match="unknown params"):
        create_strategy(StrategyConfig("a", "ema_crossover", ["X"], 5, {"fats": 3}))
    with pytest.raises(ValueError, match="fast must be < slow"):
        create_strategy(StrategyConfig("a", "ema_crossover", ["X"], 5, {"fast": 30, "slow": 10}))
    with pytest.raises(ValueError, match="unknown strategy type"):
        create_strategy(StrategyConfig("a", "nope", ["X"]))


# ---------------------------------------------------------------- engine
class Scripted(Strategy):
    """Test strategy: emits whatever list the test queues for each candle."""
    type_name = "scripted"

    def __init__(self, name="scripted", symbols=("X",), tf=5):
        super().__init__(name, list(symbols), tf, {})
        self.queue: list[list[Signal]] = []

    def on_candle(self, candle, history):
        return self.queue.pop(0) if self.queue else []


def make_engine(strats, risk=None, now=None):
    clock = [now or at(10, 0)]
    cfg = Config(risk=risk or RiskConfig(), fee_per_order=0)
    return Engine(cfg, strats, PaperBroker(), clock=lambda: clock[0], write_journal=False), clock


def candle(ts, price, sym="X", lo=None, hi=None):
    return Candle(sym, ts, price, hi or price, lo or price, price, 1)


def test_engine_entry_exit_and_pnl():
    s = Scripted()
    eng, clock = make_engine([s])
    s.queue = [[Signal.buy("X", 10, stop_loss=95)], [Signal.close("X")]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    assert eng.portfolio.qty("scripted", "X") == 10
    clock[0] = at(10, 5)
    eng.on_candle(candle(at(10, 5), 104), 5)
    assert eng.portfolio.qty("scripted", "X") == 0
    assert eng.portfolio.total_realized() == 40


def test_stop_loss_fills_at_stop_and_gap_fills_at_open():
    s = Scripted()
    eng, clock = make_engine([s])
    s.queue = [[Signal.buy("X", 10, stop_loss=98)]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    clock[0] = at(10, 10)
    eng.on_candle(Candle("X", at(10, 5), 100, 101, 97, 99, 1), 5)          # trades through the stop
    assert eng.trades[-1].price == 98 and eng.trades[-1].reason == "stop-loss"

    s.queue = [[Signal.buy("X", 10, stop_loss=98)]]
    clock[0] = at(10, 15)
    eng.on_candle(candle(at(10, 10), 100), 5)
    clock[0] = at(10, 20)
    eng.on_candle(Candle("X", at(10, 15), 95, 96, 94, 95, 1), 5)           # gaps below the stop
    assert eng.trades[-1].price == 95


def test_tick_path_builds_candles_and_stops_out():
    s = Scripted()
    eng, clock = make_engine([s])
    s.queue = [[Signal.buy("X", 10, stop_loss=99)]]
    for sec, px in [(0, 100), (60, 100.5), (300, 101)]:      # third tick closes the 10:00 candle
        clock[0] = at(10, 0) + timedelta(seconds=sec)
        eng.on_tick(Tick("X", px, clock[0]))
    assert eng.portfolio.qty("scripted", "X") == 10
    clock[0] = at(10, 6)
    eng.on_tick(Tick("X", 98.9, clock[0]))
    assert eng.portfolio.qty("scripted", "X") == 0


def test_risk_limits_reject_entries_but_never_exits():
    s = Scripted()
    eng, clock = make_engine([s], RiskConfig(max_order_value=500, max_order_qty=1000))
    s.queue = [[Signal.buy("X", 10)]]                                      # 10*100 = 1000 > 500
    eng.on_candle(candle(at(10, 0), 100), 5)
    assert eng.portfolio.qty("scripted", "X") == 0

    s.queue = [[Signal.buy("X", 4)]]
    clock[0] = at(8, 0)                                                    # before entry window
    eng.on_candle(candle(at(10, 0), 100), 5)
    assert eng.portfolio.qty("scripted", "X") == 0

    clock[0] = at(10, 0)
    s.queue = [[Signal.buy("X", 4)]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    eng.risk.halt("test")                                                  # halted: exits still work
    s.queue = [[Signal.close("X")]]
    eng.risk.halted_reason = None
    eng.on_candle(candle(at(10, 5), 100), 5)
    assert eng.portfolio.qty("scripted", "X") == 0


def test_wrong_side_stop_is_rejected():
    s = Scripted()
    eng, _ = make_engine([s])
    s.queue = [[Signal.buy("X", 1, stop_loss=105)]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    assert eng.portfolio.qty("scripted", "X") == 0


def test_square_off_and_daily_kill_switch():
    s = Scripted()
    eng, clock = make_engine([s], RiskConfig(max_daily_loss=50))
    s.queue = [[Signal.buy("X", 10)]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    clock[0] = at(10, 5)
    eng.on_candle(candle(at(10, 0), 94), 5)                                # -60 unrealised > limit
    assert eng.risk.halted_reason and eng.portfolio.qty("scripted", "X") == 0

    clock[0] = at(10, 10)
    s.queue = [[Signal.buy("X", 1)]]
    eng.on_candle(candle(at(10, 5), 94), 5)
    assert eng.portfolio.qty("scripted", "X") == 0                         # still halted

    clock[0] = at(15, 15, day=7)                                           # next day: halt cleared
    eng.on_candle(candle(at(15, 10, day=7), 94), 5)
    assert eng.risk.halted_reason is None and eng._squared_off


def test_strategies_are_isolated_from_each_other():
    a, b = Scripted("a"), Scripted("b")
    eng, clock = make_engine([a, b])
    a.queue = [[Signal.buy("X", 5)]]
    b.queue = [[Signal.sell("X", 3)]]
    eng.on_candle(candle(at(10, 0), 100), 5)
    assert eng.portfolio.qty("a", "X") == 5 and eng.portfolio.qty("b", "X") == -3
    a.queue = [[Signal.close("X")]]
    clock[0] = at(10, 5)
    eng.on_candle(candle(at(10, 5), 100), 5)
    assert eng.portfolio.qty("a", "X") == 0 and eng.portfolio.qty("b", "X") == -3
