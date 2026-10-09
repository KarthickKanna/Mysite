"""Command line interface:  python -m algotrader <login|run|backtest|strategies> ..."""
from __future__ import annotations

import argparse
import logging
import queue
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from . import auth
from .backtest import run_backtest
from .brokers.paper import PaperBroker
from .brokers.zerodha import ZerodhaBroker
from .config import load_config
from .engine import Engine, now_ist
from .feed import KiteFeed
from .history import fetch_candles, instrument_tokens, load_csv, to_ist
from .strategies import REGISTRY, create_strategy

log = logging.getLogger("algotrader")


def cmd_login(_args) -> int:
    print("1. Open and sign in:\n  ", auth.login_url())
    print("2. After login you are redirected to your app's redirect URL containing ?request_token=XXXX")
    token = input("3. Paste request_token: ").strip()
    kite = auth.complete_login(token)
    print("Logged in as", kite.profile()["user_id"], "- token saved to", auth.TOKEN_FILE)
    return 0


def cmd_strategies(_args) -> int:
    for name, cls in sorted(REGISTRY.items()):
        print(f"{name}\n  defaults: {cls.defaults}\n  {(cls.__doc__ or '').strip().splitlines()[0]}")
    return 0


def cmd_backtest(args) -> int:
    cfg = load_config(args.config)
    needs = {(sym, s.timeframe) for s in cfg.strategies if s.enabled for sym in s.symbols}
    data = {}
    if args.csv_dir:
        for sym, tf in needs:
            data[(sym, tf)] = load_csv(Path(args.csv_dir) / f"{sym}_{tf}min.csv", sym)
    else:
        kite = auth.get_kite()
        tokens = instrument_tokens(kite, cfg.exchange, sorted({s for s, _ in needs}))
        end = to_ist(datetime.fromisoformat(args.end)) if args.end else now_ist()
        start = to_ist(datetime.fromisoformat(args.start)) if args.start else end - timedelta(days=30)
        for sym, tf in sorted(needs):
            log.info("fetching %s %dm %s -> %s", sym, tf, start.date(), end.date())
            data[(sym, tf)] = fetch_candles(kite, tokens[sym], sym, tf, start, end)
    _, report = run_backtest(cfg, data, args.slippage)
    print(report.format())
    return 0


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    strategies = [create_strategy(s) for s in cfg.strategies if s.enabled]
    if not strategies:
        print("no enabled strategies in config", file=sys.stderr)
        return 2
    kite = auth.get_kite()  # market data needs a session even in paper mode
    if args.live:
        broker = ZerodhaBroker(kite, cfg.exchange, cfg.product)
        log.warning("LIVE MODE: real orders will be placed (exchange=%s product=%s)", cfg.exchange, cfg.product)
    else:
        broker = PaperBroker()
        log.info("paper mode: no real orders will be placed (use --live to trade for real)")
    engine = Engine(cfg, strategies, broker)

    tokens = instrument_tokens(kite, cfg.exchange, engine.symbols)
    # warm up indicators with recent history so strategies can trade from the first candle
    today = now_ist()
    for (sym, tf), strats in engine.feeds.items():
        need = max(s.min_history for s in strats)
        if need:
            days = -(-need * tf // 375) * 2 + 3  # 375 trading minutes/day, x2 for weekends/holidays
            candles = fetch_candles(kite, tokens[sym], sym, tf, today - timedelta(days=days), today)
            engine.preload(sym, tf, [c for c in candles if c.ts + timedelta(minutes=tf) <= today])

    ticks: queue.Queue = queue.Queue()
    feed = KiteFeed(auth.credentials()[0], kite.access_token, tokens, ticks.put)
    feed.start()
    log.info("engine running: %s", ", ".join(s.name for s in strategies))
    try:
        while True:
            try:
                engine.on_tick(ticks.get(timeout=1.0))
            except queue.Empty:
                engine.housekeeping()  # square-off / kill switch still fire when the market is quiet
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        feed.stop()
        if not args.keep_positions:
            engine.square_off_all("shutdown")
        for strat, sym, pos in engine.portfolio.open_positions():
            log.warning("OPEN POSITION LEFT: %s %s qty=%d avg=%.2f", strat, sym, pos.qty, pos.avg_price)
        log.info("realised pnl today: %.2f", engine.portfolio.total_realized())
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="algotrader")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="interactive Kite login").set_defaults(fn=cmd_login)
    sub.add_parser("strategies", help="list available strategy types").set_defaults(fn=cmd_strategies)

    r = sub.add_parser("run", help="run strategies on live market data (paper unless --live)")
    r.add_argument("-c", "--config", default="config.yaml")
    r.add_argument("--live", action="store_true", help="place REAL orders")
    r.add_argument("--keep-positions", action="store_true", help="do not square off on Ctrl-C")
    r.set_defaults(fn=cmd_run)

    b = sub.add_parser("backtest", help="replay historical candles through the strategies")
    b.add_argument("-c", "--config", default="config.yaml")
    b.add_argument("--csv-dir", help="use CSVs named <SYMBOL>_<tf>min.csv instead of the Kite API")
    b.add_argument("--start", help="ISO date/time (Kite source)")
    b.add_argument("--end", help="ISO date/time (Kite source)")
    b.add_argument("--slippage", type=float, default=0.0, help="fraction, e.g. 0.0005 = 5 bps per fill")
    b.set_defaults(fn=cmd_backtest)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")
    try:
        return args.fn(args)
    except (auth.AuthError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
