"""Hard-coded risk gate. Rules in code, not judgement calls.

The gate sits between every signal and every order. It can only block or
approve; it never modifies the rule. Sizing (95% deployment) is enforced in
ledger.buy, so this module handles the circuit breakers.
"""

from dataclasses import dataclass

from agent.config import DAILY_LOSS_HALT, KILL_SWITCH_DRAWDOWN


@dataclass(frozen=True)
class GateResult:
    approved: bool
    block_reason: str | None = None
    trip_kill_switch: bool = False
    trip_daily_halt: bool = False


def kill_switch_tripped(equity: float, starting_capital: float) -> bool:
    """Catastrophic circuit breaker: equity down >25% from starting capital."""
    return equity < starting_capital * (1 - KILL_SWITCH_DRAWDOWN)


def daily_loss_exceeded(prev_equity: float, equity: float) -> bool:
    """Single-day loss >10% of account value."""
    if prev_equity <= 0:
        return False
    return (prev_equity - equity) / prev_equity > DAILY_LOSS_HALT


def gate(
    signal: str,
    equity: float,
    prev_equity: float,
    starting_capital: float,
    kill_switch_already_tripped: bool,
    halted: bool,
) -> GateResult:
    if kill_switch_already_tripped:
        return GateResult(False, "kill_switch: previously tripped, manual review required")
    if kill_switch_tripped(equity, starting_capital):
        return GateResult(
            False,
            f"kill_switch: equity {equity:.2f} below {(1 - KILL_SWITCH_DRAWDOWN):.0%} of starting capital",
            trip_kill_switch=True,
        )
    if halted:
        return GateResult(False, "daily_halt: still within 24h pause")
    if daily_loss_exceeded(prev_equity, equity):
        return GateResult(
            False,
            f"daily_halt: single-day loss exceeded {DAILY_LOSS_HALT:.0%}",
            trip_daily_halt=True,
        )
    if signal == "hold":
        return GateResult(True)  # approved but nothing to execute
    return GateResult(True)
