from datetime import time

from algotrader.backtest import run_backtest
from algotrader.config import Config, RiskConfig, StrategyConfig
from tests.conftest import synthetic_candles


def test_multi_strategy_backtest_runs_and_flattens_each_day():
    cfg = Config(
        risk=RiskConfig(max_daily_loss=1e9, max_order_value=1e9, max_strategy_capital=1e9),
        strategies=[
            StrategyConfig("ema", "ema_crossover", ["AAA"], 5, {"fast": 5, "slow": 13, "quantity": 10}),
            StrategyConfig("rsi", "rsi_reversion", ["BBB"], 15, {"quantity": 10, "oversold": 40}),
            StrategyConfig("orb", "opening_range_breakout", ["AAA"], 5, {"quantity": 10}),
        ],
    )
    data = {
        ("AAA", 5): synthetic_candles("AAA", days=8, tf=5, seed=3, vol=0.003),
        ("BBB", 15): synthetic_candles("BBB", days=8, tf=15, seed=4, vol=0.004),
    }
    engine, report = run_backtest(cfg, data)
    assert report.trades, "expected some trades"
    assert set(report.per_strategy) <= {"ema", "rsi", "orb"} and len(report.per_strategy) >= 2
    assert not list(engine.portfolio.open_positions())          # everything flat at the end
    # intraday product: no position is ever carried overnight
    assert all(t.ts.time() <= time(15, 30) for t in report.trades)
    assert abs(report.total_pnl - engine.portfolio.total_realized()) < 1e-6


def test_orb_trades_at_most_once_per_symbol_per_day():
    cfg = Config(risk=RiskConfig(max_daily_loss=1e9, max_order_value=1e9, max_strategy_capital=1e9),
                 strategies=[StrategyConfig("orb", "opening_range_breakout", ["AAA"], 5, {"quantity": 1})])
    candles = synthetic_candles("AAA", days=10, tf=5, seed=11, vol=0.004)
    _, report = run_backtest(cfg, {("AAA", 5): candles})
    entries = {}
    for t in report.trades:
        if t.realized == 0:
            entries[t.ts.date()] = entries.get(t.ts.date(), 0) + 1
    assert entries and max(entries.values()) == 1
