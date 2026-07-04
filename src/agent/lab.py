"""The Lab: the proving ground for strategies, at machine speed.

Two studies:
  python -m agent.lab regimes [SYMBOL]   — every strategy vs baseline, per market era
  python -m agent.lab fees [SYMBOL]      — the roster under different cost assumptions

The Lab never touches the live experiment. Its job is to expose strategies
that only work in one regime or only at fantasy fees, and to audition
candidates before they can be pre-registered and promoted to the live roster.
"""

import sys
from datetime import date

from agent import data, ledger
from agent.config import STARTING_CAPITAL, SYMBOL
from agent.metrics import max_drawdown, sharpe
from agent.strategies import AGENTS, MAX_WARMUP

# Historical eras with distinct market character. Alpaca crypto data reaches
# back to ~2021, which conveniently covers one full boom-bust-recovery cycle.
REGIMES = [
    ("2021 late-bull + top", date(2021, 6, 1), date(2021, 12, 31)),
    ("2022 crash",           date(2022, 1, 1), date(2022, 12, 31)),
    ("2023 recovery",        date(2023, 1, 1), date(2023, 12, 31)),
    ("2024 bull run",        date(2024, 1, 1), date(2024, 12, 31)),
    ("2025-26 recent",       date(2025, 1, 1), date(2026, 7, 1)),
]


def simulate(closes_dated, strat, cost_rate=None, start_idx=None):
    """Run one strategy over dated closes. Returns (equity_curve, trades)."""
    prices = [c for _, c in closes_dated]
    start = start_idx if start_idx is not None else strat.warmup
    port = ledger.Portfolio(cash=STARTING_CAPITAL)
    curve, trades = [], 0
    for i in range(start, len(closes_dated)):
        price = prices[i]
        res = strat.evaluate(prices[: i + 1], port.position)
        if res.signal == "buy":
            port, _ = ledger.buy(port, price, cost_rate=cost_rate)
            trades += 1
        elif res.signal == "sell":
            port, _ = ledger.sell_all(port, price, cost_rate=cost_rate)
            trades += 1
        port, eq, _ = ledger.mark(port, price)
        curve.append(eq)
    return curve, trades


def simulate_baseline(closes_dated, cost_rate=None, start_idx=None):
    prices = [c for _, c in closes_dated]
    start = start_idx if start_idx is not None else 0
    port = ledger.Portfolio(cash=STARTING_CAPITAL)
    curve = []
    for i in range(start, len(closes_dated)):
        if port.position == "flat":
            port, _ = ledger.buy(port, prices[i], cost_rate=cost_rate)
        port, eq, _ = ledger.mark(port, prices[i])
        curve.append(eq)
    return curve


def _row(name, curve, trades):
    ret = curve[-1] / STARTING_CAPITAL - 1
    return f"{name:12s} {ret:+9.1%} {max_drawdown(curve):7.1%} {sharpe(curve):7.2f} {trades:>7}"


def regimes_study(symbol: str) -> None:
    all_closes = data.get_daily_closes(2200, symbol)  # everything Alpaca has
    print(f"data available: {all_closes[0][0]} -> {all_closes[-1][0]} ({len(all_closes)} bars)\n")
    for label, start, end in REGIMES:
        # include warmup bars before the era so day one of the era is evaluable
        era_start_idx = next((i for i, (d, _) in enumerate(all_closes) if d >= start), None)
        if era_start_idx is None or era_start_idx < MAX_WARMUP:
            print(f"== {label}: insufficient data, skipped ==\n")
            continue
        window = [x for x in all_closes[: len(all_closes)] if x[0] <= end]
        if not window or window[-1][0] < start:
            print(f"== {label}: insufficient data, skipped ==\n")
            continue
        end_idx = len(window)
        sliced = all_closes[:end_idx]
        px0 = sliced[era_start_idx][1]
        pxN = sliced[-1][1]
        print(f"== {label}  ({sliced[era_start_idx][0]} -> {sliced[-1][0]}, "
              f"BTC {pxN / px0 - 1:+.0%}) ==")
        print(f"{'agent':12s} {'return':>9s} {'maxDD':>7s} {'sharpe':>7s} {'trades':>7s}")
        for key, strat in AGENTS.items():
            curve, trades = simulate(sliced, strat, start_idx=era_start_idx)
            print(_row(key, curve, trades))
        print(_row("baseline", simulate_baseline(sliced, start_idx=era_start_idx), 1))
        print()


def fees_study(symbol: str) -> None:
    closes = data.get_daily_closes(3 * 365 + MAX_WARMUP, symbol)
    print(f"window: {closes[MAX_WARMUP][0]} -> {closes[-1][0]}\n")
    for rate in (0.0015, 0.0035, 0.0060):
        print(f"== per-side cost {rate:.2%} ==")
        print(f"{'agent':12s} {'return':>9s} {'maxDD':>7s} {'sharpe':>7s} {'trades':>7s}")
        for key, strat in AGENTS.items():
            curve, trades = simulate(closes, strat, cost_rate=rate, start_idx=MAX_WARMUP)
            print(_row(key, curve, trades))
        print(_row("baseline", simulate_baseline(closes, cost_rate=rate, start_idx=MAX_WARMUP), 1))
        print()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "regimes"
    sym = sys.argv[2] if len(sys.argv) > 2 else SYMBOL
    (regimes_study if mode == "regimes" else fees_study)(sym)
