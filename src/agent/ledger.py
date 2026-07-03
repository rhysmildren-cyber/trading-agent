"""Simulated portfolio ledger — the source of truth for equity and P&L.

Alpaca's paper account does not apply our cost model, so all performance math
lives here. Both the strategy and the baseline run on this same ledger code.
"""

from dataclasses import dataclass, replace

from agent import costs
from agent.config import DEPLOY_FRACTION


@dataclass(frozen=True)
class Portfolio:
    cash: float
    qty: float = 0.0
    peak_equity: float = 0.0

    @property
    def position(self) -> str:
        return "long" if self.qty > 0 else "flat"

    def equity(self, price: float) -> float:
        return self.cash + self.qty * price


def buy(p: Portfolio, price: float, deploy_fraction: float = DEPLOY_FRACTION) -> tuple[Portfolio, dict]:
    """Deploy deploy_fraction of current equity into BTC; keep the rest as buffer."""
    budget = p.equity(price) * deploy_fraction
    if budget > p.cash:
        budget = p.cash  # never spend cash we don't have
    qty, paid = costs.buy_with_cash(budget, price)
    new = replace(p, cash=p.cash - budget, qty=p.qty + qty)
    fill = {"side": "buy", "qty": qty, "price": price, "fee_paid": paid}
    return new, fill


def sell_all(p: Portfolio, price: float) -> tuple[Portfolio, dict]:
    proceeds, paid = costs.sell_qty(p.qty, price)
    new = replace(p, cash=p.cash + proceeds, qty=0.0)
    fill = {"side": "sell", "qty": p.qty, "price": price, "fee_paid": paid}
    return new, fill


def mark(p: Portfolio, price: float) -> tuple[Portfolio, float, float]:
    """End-of-day mark: returns (portfolio with updated peak, equity, drawdown_pct)."""
    eq = p.equity(price)
    peak = max(p.peak_equity, eq)
    dd = 0.0 if peak == 0 else (peak - eq) / peak
    return replace(p, peak_equity=peak), eq, dd
