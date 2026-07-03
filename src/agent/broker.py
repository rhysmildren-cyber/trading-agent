"""Thin Alpaca paper-order wrapper.

Orders are placed for execution realism only; the simulated ledger is the
source of truth for equity. Paper endpoint is hard-coded — this module can
never touch a live account.
"""

import os

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from agent.config import SYMBOL


def _client() -> TradingClient:
    return TradingClient(
        api_key=os.environ["APCA_API_KEY_ID"],
        secret_key=os.environ["APCA_API_SECRET_KEY"],
        paper=True,
    )


def place_market_order(side: str, qty: float) -> str:
    order = _client().submit_order(
        MarketOrderRequest(
            symbol=SYMBOL,
            qty=round(qty, 8),
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
        )
    )
    return str(order.id)
