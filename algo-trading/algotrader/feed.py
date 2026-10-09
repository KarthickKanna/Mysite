"""Live tick feed from Kite's websocket (KiteTicker)."""
from __future__ import annotations

import logging
from typing import Callable

from kiteconnect import KiteTicker

from .history import to_ist
from .engine import now_ist
from .models import Tick

log = logging.getLogger(__name__)


class KiteFeed:
    def __init__(self, api_key: str, access_token: str, tokens: dict[str, int], on_tick: Callable[[Tick], None]):
        self._by_token = {t: s for s, t in tokens.items()}
        self._on_tick = on_tick
        self._ticker = KiteTicker(api_key, access_token)
        self._ticker.on_connect = self._connected
        self._ticker.on_ticks = self._ticks
        self._ticker.on_close = lambda ws, code, reason: log.warning("ticker closed: %s %s", code, reason)
        self._ticker.on_error = lambda ws, code, reason: log.error("ticker error: %s %s", code, reason)
        self._ticker.on_reconnect = lambda ws, n: log.warning("ticker reconnecting (attempt %s)", n)

    def _connected(self, ws, _response) -> None:
        toks = list(self._by_token)
        ws.subscribe(toks)
        ws.set_mode(ws.MODE_FULL, toks)  # FULL carries exchange_timestamp + cumulative volume
        log.info("subscribed to %d instruments", len(toks))

    def _ticks(self, _ws, ticks) -> None:
        for t in ticks:
            sym = self._by_token.get(t["instrument_token"])
            if sym is None or "last_price" not in t:
                continue
            ts = to_ist(t["exchange_timestamp"]) if t.get("exchange_timestamp") else now_ist()
            self._on_tick(Tick(sym, float(t["last_price"]), ts, t.get("volume_traded")))

    def start(self) -> None:
        """Connect in a background thread."""
        self._ticker.connect(threaded=True)

    def stop(self) -> None:
        self._ticker.close()
