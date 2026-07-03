"""The daily loop. Run once per day at 00:05 UTC by GitHub Actions.

Idempotent per UTC date: a second run on the same date no-ops.

Flow: fetch data -> SMA signal -> risk gate -> (paper order + ledger update)
      -> log decision/trade/equity for both systems -> daily review row.
"""

import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from agent import broker, data, db, ledger, review, risk, signal
from agent.config import SMA_WINDOW, STRATEGY_VERSION, SYMBOL, SYSTEM_BASELINE, SYSTEM_STRATEGY

EXECUTE_ORDERS = "--execute" in sys.argv  # signal-only mode until step 7 sign-off


def run() -> None:
    load_dotenv()
    conn = db.client()
    now = datetime.now(timezone.utc)

    closes = data.get_daily_closes(SMA_WINDOW + 10)
    bar_date, price = closes[-1]
    run_date = bar_date  # decisions are keyed by the bar they act on

    if db.decision_exists(conn, run_date):
        print(f"decision for {run_date} already recorded — no-op")
        return

    sma = signal.compute_sma([c for _, c in closes])

    # --- strategy ---
    state = db.get_state(conn, SYSTEM_STRATEGY)
    port = db.portfolio_from_state(state)
    sig = signal.evaluate(price, sma, port.position)

    prev_eq = db.prev_equity(conn, SYSTEM_STRATEGY) or float(state["starting_capital"])
    halted = state["halted_until"] is not None and datetime.fromisoformat(
        state["halted_until"].replace("Z", "+00:00")
    ) > now
    gate = risk.gate(
        signal=sig.signal,
        equity=port.equity(price),
        prev_equity=prev_eq,
        starting_capital=float(state["starting_capital"]),
        kill_switch_already_tripped=bool(state["kill_switch_tripped"]),
        halted=halted,
    )

    state_extra: dict = {}
    if gate.trip_kill_switch:
        state_extra["kill_switch_tripped"] = True
        db.log_event(conn, "kill_switch", gate.block_reason or "")
    if gate.trip_daily_halt:
        state_extra["halted_until"] = (now + timedelta(hours=24)).isoformat()
        db.log_event(conn, "daily_halt", gate.block_reason or "")

    action = "no-change"
    if sig.signal in ("buy", "sell") and gate.approved:
        eq_before = port.equity(price)
        if sig.signal == "buy":
            port, fill = ledger.buy(port, price)
        else:
            port, fill = ledger.sell_all(port, price)
        order_id = None
        if EXECUTE_ORDERS:
            order_id = broker.place_market_order(fill["side"], fill["qty"])
        db.log_trade(conn, {
            "strategy_version": STRATEGY_VERSION,
            "symbol": SYMBOL,
            "side": fill["side"],
            "qty": fill["qty"],
            "price": fill["price"],
            "fee_paid": fill["fee_paid"],
            "account_value_before": eq_before,
            "account_value_after": port.equity(price),
            "rationale": f"close {price:.2f} vs sma50 {sma:.2f} ({sig.signal}); alpaca_order={order_id}",
        })
        action = "executed" if EXECUTE_ORDERS else "simulated"
    elif sig.signal in ("buy", "sell"):
        action = "blocked"

    db.log_decision(conn, {
        "run_date": run_date.isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "price": price,
        "sma_50": sma,
        "in_deadband": sig.in_deadband,
        "signal": sig.signal,
        "position_before": state["position"],
        "action_taken": action,
        "block_reason": gate.block_reason,
    })

    port, eq, dd = ledger.mark(port, price)
    db.save_portfolio(conn, SYSTEM_STRATEGY, port, **state_extra)
    db.log_equity(conn, run_date, SYSTEM_STRATEGY, eq, dd, port.position)

    # --- baseline: buy once on first run, then just mark to market ---
    b_state = db.get_state(conn, SYSTEM_BASELINE)
    b_port = db.portfolio_from_state(b_state)
    if b_port.position == "flat" and db.prev_equity(conn, SYSTEM_BASELINE) is None:
        b_port, b_fill = ledger.buy(b_port, price)
        db.log_event(conn, "baseline_entry", f"bought {b_fill['qty']:.8f} @ {price:.2f}")
    b_port, b_eq, b_dd = ledger.mark(b_port, price)
    db.save_portfolio(conn, SYSTEM_BASELINE, b_port)
    db.log_equity(conn, run_date, SYSTEM_BASELINE, b_eq, b_dd, b_port.position)

    rules_followed = not (sig.signal in ("buy", "sell") and not gate.approved and action == "executed")
    review.write_daily_review(conn, run_date, rules_followed,
                              notes=gate.block_reason or "")

    print(f"{run_date} price={price:.2f} sma={sma:.2f} signal={sig.signal} "
          f"action={action} strategy_eq={eq:.2f} baseline_eq={b_eq:.2f}")


if __name__ == "__main__":
    run()
