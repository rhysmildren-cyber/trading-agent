"""Cost model: every simulated fill pays fee + slippage on notional, both sides."""

from agent.config import COST_RATE


def buy_with_cash(cash_budget: float, price: float, cost_rate: float = COST_RATE) -> tuple[float, float]:
    """Spend cash_budget buying at price. Returns (qty acquired, costs paid)."""
    costs = cash_budget * cost_rate
    qty = (cash_budget - costs) / price
    return qty, costs


def sell_qty(qty: float, price: float, cost_rate: float = COST_RATE) -> tuple[float, float]:
    """Sell qty at price. Returns (cash received, costs paid)."""
    gross = qty * price
    costs = gross * cost_rate
    return gross - costs, costs
