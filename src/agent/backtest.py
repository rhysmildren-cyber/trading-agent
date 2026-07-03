"""Backtest: the same engine (signal -> costs -> ledger) over historical daily closes.

Run once, exactly as specced — a bug-finder and expectation-setter, not an
optimizer. No parameters are tuned here.

Usage: python -m agent.backtest [years]
"""

import csv
import math
import sys
from pathlib import Path

from agent import data, ledger, signal
from agent.config import SMA_WINDOW, STARTING_CAPITAL


def max_drawdown(equities: list[float]) -> float:
    peak, worst = equities[0], 0.0
    for e in equities:
        peak = max(peak, e)
        worst = max(worst, (peak - e) / peak)
    return worst


def sharpe(equities: list[float]) -> float:
    rets = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities))]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else (mean / sd) * math.sqrt(365)


def run(years: float = 3.0) -> None:
    days = int(years * 365) + SMA_WINDOW
    closes = data.get_daily_closes(days)
    if len(closes) < SMA_WINDOW + 30:
        raise SystemExit(f"not enough history: {len(closes)} bars")

    strat = ledger.Portfolio(cash=STARTING_CAPITAL)
    base = ledger.Portfolio(cash=STARTING_CAPITAL)
    trades = 0
    rows = []

    prices = [c for _, c in closes]
    for i in range(SMA_WINDOW, len(closes)):
        day, price = closes[i]
        sma = signal.compute_sma(prices[: i + 1])

        if base.position == "flat":  # baseline buys once, on the first evaluable day
            base, _ = ledger.buy(base, price)

        sig = signal.evaluate(price, sma, strat.position)
        if sig.signal == "buy":
            strat, _ = ledger.buy(strat, price)
            trades += 1
        elif sig.signal == "sell":
            strat, _ = ledger.sell_all(strat, price)
            trades += 1

        strat, s_eq, _ = ledger.mark(strat, price)
        base, b_eq, _ = ledger.mark(base, price)
        rows.append((day, price, sma, sig.signal, strat.position, s_eq, b_eq))

    s_curve = [r[5] for r in rows]
    b_curve = [r[6] for r in rows]

    out = Path("backtest_output")
    out.mkdir(exist_ok=True)
    with open(out / "equity.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "price", "sma50", "signal", "position", "strategy_equity", "baseline_equity"])
        w.writerows(rows)

    def report(name: str, curve: list[float]) -> str:
        ret = curve[-1] / STARTING_CAPITAL - 1
        return (f"{name:9s} return={ret:+8.1%}  maxDD={max_drawdown(curve):6.1%}  "
                f"sharpe={sharpe(curve):5.2f}  final=${curve[-1]:,.0f}")

    print(f"Backtest {rows[0][0]} -> {rows[-1][0]}  ({len(rows)} days, {trades} trades)")
    print(report("strategy", s_curve))
    print(report("baseline", b_curve))
    px_ret = rows[-1][1] / rows[0][1] - 1
    print(f"raw BTC price change over period: {px_ret:+.1%} (sanity check vs baseline)")
    print(f"detail: backtest_output/equity.csv")


if __name__ == "__main__":
    run(float(sys.argv[1]) if len(sys.argv) > 1 else 3.0)
