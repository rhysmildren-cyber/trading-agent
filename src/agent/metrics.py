"""Shared performance metrics — used by both the backtest and the dashboard."""

import math


def total_return(equities: list[float]) -> float:
    if len(equities) < 2:
        return 0.0
    return equities[-1] / equities[0] - 1


def max_drawdown(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak, worst = equities[0], 0.0
    for e in equities:
        peak = max(peak, e)
        worst = max(worst, (peak - e) / peak)
    return worst


def sharpe(equities: list[float]) -> float:
    """Daily returns, risk-free 0, annualized x sqrt(365)."""
    rets = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else (mean / sd) * math.sqrt(365)
