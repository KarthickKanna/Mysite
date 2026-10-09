# algotrader — multi-strategy algo trading on Zerodha (Kite Connect)

Run several independent strategies side by side on one shared engine, with common risk
controls. **Paper trading is the default**; real orders need an explicit `--live`.

```
ticks (KiteTicker) ─▶ CandleAggregator ─▶ Strategy.on_candle ─▶ Signal
                                                                  │
         Portfolio (per-strategy P&L) ◀─ Broker ◀─ RiskManager ◀──┘
                                         (Paper | Zerodha)
```

The same `Engine` and strategy code run in **live**, **paper** and **backtest**; only the broker and the
candle source change.

## Setup

```bash
cd algo-trading
pip install -r requirements.txt
cp .env.example .env              # add KITE_API_KEY / KITE_API_SECRET from developers.kite.trade
cp config.example.yaml config.yaml
python -m algotrader login        # daily: sign in, paste request_token (token valid till ~6am next day)
```

Kite Connect needs a paid developer app with the Historical Data add-on for history/backtesting from the API.
The login is interactive on purpose (password + 2FA); this project does not automate it.

## Commands

| Command | What it does |
|---|---|
| `python -m algotrader strategies` | list strategy types and their default params |
| `python -m algotrader backtest -c config.yaml --start 2025-01-01 --end 2025-03-01` | replay Kite history |
| `python -m algotrader backtest -c config.yaml --csv-dir data/` | replay CSVs named `<SYMBOL>_<tf>min.csv` (`datetime,open,high,low,close,volume`) |
| `python -m algotrader run -c config.yaml` | **paper** trade on live ticks |
| `python -m algotrader run -c config.yaml --live` | **real orders** |

Suggested path: backtest → paper for a few weeks → live with minimum quantity.

## Adding a strategy

```python
# algotrader/strategies/my_strategy.py   (import it in strategies/__init__.py)
from . import register
from .base import Strategy
from ..models import Signal

@register
class MyStrategy(Strategy):
    type_name = "my_strategy"
    defaults = {"quantity": 1}                 # YAML `params:` override these; unknown keys are rejected

    def on_candle(self, candle, history):      # called per closed candle; history[-1] is `candle`
        if self.position(candle.symbol) == 0 and candle.close > history[-2].high:
            return [Signal.buy(candle.symbol, self.p.quantity, stop_loss=candle.close * 0.99)]
        return []
```

Then add it to `config.yaml` under `strategies:` with its own `symbols`, `timeframe` and `params`.
Signals: `Signal.buy/sell(symbol, qty, stop_loss=…)` and `Signal.close(symbol)`. A signal opposite to an
open position only reduces it; to reverse, return `[Signal.close(...), Signal.buy(...)]`.
Each strategy has its own position book, so two strategies can hold opposite views on one symbol
(Zerodha nets them at the broker; the engine keeps per-strategy P&L).

Bundled examples: `ema_crossover` (trend), `rsi_reversion` (mean reversion), `opening_range_breakout`.
They are illustrations of the framework, **not profitable-by-default strategies**.

## Risk controls (`risk:` in config, apply to all strategies)

Per-order value/quantity caps · max open positions · per-strategy gross capital · entry time window ·
scheduled square-off · **daily loss kill switch** (squares everything off and halts until the next day) ·
stop-loss validation. Exits are never blocked by risk checks. If a live order's fill can't be confirmed,
new entries halt until you investigate.

## Known limitations — read before going live

* **Stop-losses are software-side**: enforced by this process on ticks. If the process or your connection
  dies, no stop is working. (MIS positions are auto-squared by Zerodha ~15:20.) Exchange-side SL orders are
  not implemented.
* Orders are MARKET only. Live fills are confirmed by polling `order_history` (5 s timeout).
* No restart recovery: positions are tracked in memory. After a crash, reconcile with the Kite positions page.
* On startup mid-session the first live candle is partial; history is preloaded for indicator warm-up.
* Backtests fill at candle close, assume the stop beats the target within one candle, and ignore taxes/impact.
* Orders are processed on one thread; a slow Kite response delays tick handling by up to the fill timeout.
* Algo trading rules (SEBI/exchange, Zerodha API terms, static-IP requirements for order APIs) change;
  check the current requirements for your account. This is not financial advice; you are responsible for
  every order it places.

## Tests

```bash
python -m pytest -q
```
