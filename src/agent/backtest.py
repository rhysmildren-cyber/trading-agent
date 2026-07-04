"""Backtest the whole roster over the same window — one shared start line.

Purpose: validate each strategy implementation and record pre-registered
expectations. Run once, exactly as specced; parameters do not move afterward.

Usage: python -m agent.backtest [years]
"""

import csv
import sys
from pathlib import Path

from agent import data, ledger
from agent.config import STARTING_CAPITAL
from agent.metrics import max_drawdown, sharpe
from agent.strategies import AGENTS, MAX_WARMUP


def run(years: float = 3.0) -> None:
    days = int(years * 365) + MAX_WARMUP
    closes_dated = data.get_daily_closes(days)
    if len(closes_dated) < MAX_WARMUP + 30:
        raise SystemExit(f"not enough history: {len(closes_dated)} bars")
    prices = [c for _, c in closes_dated]

    ports = {k: ledger.Portfolio(cash=STARTING_CAPITAL) for k in AGENTS}
    base = ledger.Portfolio(cash=STARTING_CAPITAL)
    trades = {k: 0 for k in AGENTS}
    curves: dict[str, list[float]] = {k: [] for k in [*AGENTS, "baseline"]}
    rows = []

    for i in range(MAX_WARMUP, len(closes_dated)):
        day, price = closes_dated[i]
        window = prices[: i + 1]

        if base.position == "flat":
            base, _ = ledger.buy(base, price)

        for key, strat in AGENTS.items():
            res = strat.evaluate(window, ports[key].position)
            if res.signal == "buy":
                ports[key], _ = ledger.buy(ports[key], price)
                trades[key] += 1
            elif res.signal == "sell":
                ports[key], _ = ledger.sell_all(ports[key], price)
                trades[key] += 1
            ports[key], eq, _ = ledger.mark(ports[key], price)
            curves[key].append(eq)

        base, b_eq, _ = ledger.mark(base, price)
        curves["baseline"].append(b_eq)
        rows.append([day, price] + [f"{curves[k][-1]:.2f}" for k in curves])

    out = Path("backtest_output")
    out.mkdir(exist_ok=True)
    with open(out / "equity.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "price", *curves.keys()])
        w.writerows(rows)

    n = len(rows)
    print(f"Backtest {rows[0][0]} -> {rows[-1][0]}  ({n} days)\n")
    print(f"{'agent':10s} {'return':>9s} {'maxDD':>7s} {'sharpe':>7s} {'trades':>7s} {'final':>12s}")
    for k, curve in curves.items():
        ret = curve[-1] / STARTING_CAPITAL - 1
        t = trades.get(k, 1 if k == "baseline" else 0)
        print(f"{k:10s} {ret:+9.1%} {max_drawdown(curve):7.1%} {sharpe(curve):7.2f} "
              f"{t:7d} ${curve[-1]:>11,.0f}")
    px_ret = rows[-1][1] / rows[0][1] - 1
    print(f"\nraw BTC price change over period: {px_ret:+.1%} (sanity check vs baseline)")
    print("detail: backtest_output/equity.csv")


if __name__ == "__main__":
    run(float(sys.argv[1]) if len(sys.argv) > 1 else 3.0)
