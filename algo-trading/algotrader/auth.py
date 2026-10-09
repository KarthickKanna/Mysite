"""Kite Connect login.

Zerodha requires an interactive login (password + 2FA) to obtain a `request_token`;
the resulting access_token is valid until ~06:00 IST next day. This module does NOT
automate the login form: you open the login URL, sign in, and paste the request_token
from the redirect URL (`algotrader login`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from kiteconnect import KiteConnect

TOKEN_FILE = Path(os.environ.get("KITE_TOKEN_FILE", ".kite_token.json"))


class AuthError(RuntimeError):
    pass


def credentials() -> tuple[str, str]:
    key, secret = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_API_SECRET")
    if not key or not secret:
        raise AuthError("set KITE_API_KEY and KITE_API_SECRET (see .env.example)")
    return key, secret


def login_url() -> str:
    return KiteConnect(api_key=credentials()[0]).login_url()


def complete_login(request_token: str) -> KiteConnect:
    key, secret = credentials()
    kite = KiteConnect(api_key=key)
    session = kite.generate_session(request_token, api_secret=secret)
    kite.set_access_token(session["access_token"])
    TOKEN_FILE.write_text(json.dumps({"access_token": session["access_token"]}))
    TOKEN_FILE.chmod(0o600)
    return kite


def get_kite() -> KiteConnect:
    """KiteConnect client using today's saved token; raises AuthError if missing/expired."""
    key, _ = credentials()
    if not TOKEN_FILE.exists():
        raise AuthError("not logged in; run `python -m algotrader login`")
    kite = KiteConnect(api_key=key)
    kite.set_access_token(json.loads(TOKEN_FILE.read_text())["access_token"])
    try:
        kite.profile()
    except Exception as e:
        raise AuthError(f"saved token rejected ({e}); run `python -m algotrader login`") from e
    return kite
