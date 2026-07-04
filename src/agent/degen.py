"""Degen Wing mechanics: simulated leverage and shorting, with liquidation.

Deliberately simplified perp-style model, documented honestly:
- Enter with notional = leverage x 95% of equity; fees paid on the FULL notional.
- Daily mark: equity moves by qty x price change; funding accrues on notional.
- Liquidation when equity falls to 10% of entry equity; the exchange keeps
  half of what's left (penalty). Liquidated agents stay dead.

Caveat (also shown on the dashboard): real leverage is crueller than this —
daily bars hide intraday wicks that would liquidate sooner. These agents are
education and entertainment, not evidence.
"""

from dataclasses import dataclass

from agent.config import COST_RATE, DEPLOY_FRACTION

FUNDING_DAILY = 0.0003        # ~11%/yr on notional while positioned
LIQ_FRACTION = 0.10           # equity <= 10% of entry equity -> liquidated
LIQ_HAIRCUT = 0.5             # exchange keeps half of the scraps


@dataclass(frozen=True)
class DegenFill:
    side: str
    qty: float                 # signed: negative = short
    price: float
    fee_paid: float
    notional: float


def open_position(equity: float, price: float, leverage: float, direction: int,
                  cost_rate: float = COST_RATE) -> tuple[float, float, DegenFill]:
    """Returns (new_equity, signed_qty, fill)."""
    notional = equity * DEPLOY_FRACTION * leverage
    fee = notional * cost_rate
    qty = direction * notional / price
    return equity - fee, qty, DegenFill("buy", qty, price, fee, notional)


def close_position(equity: float, qty: float, price: float,
                   cost_rate: float = COST_RATE) -> tuple[float, DegenFill]:
    notional = abs(qty) * price
    fee = notional * cost_rate
    return equity - fee, DegenFill("sell", qty, price, fee, notional)


def mark(equity: float, qty: float, price: float, prev_price: float) -> float:
    """Daily mark-to-market plus funding drag while positioned."""
    if qty == 0:
        return equity
    equity += qty * (price - prev_price)
    equity -= abs(qty) * price * FUNDING_DAILY
    return equity


def is_liquidated(equity: float, entry_equity: float) -> bool:
    return equity <= entry_equity * LIQ_FRACTION


def liquidate(equity: float) -> float:
    """What's left after the forced close and penalty."""
    return max(equity * LIQ_HAIRCUT, 0.0)
