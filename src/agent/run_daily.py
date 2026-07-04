"""The daily loop, swarm edition. Runs once per day at 00:05 UTC via GitHub Actions.

For each agent in the registry: evaluate its strategy -> risk gate -> ledger op
-> log decision/trade/equity. One shared baseline. Idempotent per (bar date,
agent): a second run on the same date no-ops.

Only KEPLER places ceremonial Alpaca paper orders, and only with --execute
(signal-only until PRD step-7 sign-off).
"""

import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from agent import broker, data, db, ledger, review, risk
from agent.config import STRATEGY_VERSION, SYMBOL
from agent.strategies import AGENTS, BASELINE_KEY, MAX_WARMUP

EXECUTE_ORDERS = "--execute" in sys.argv


def run() -> None:
    load_dotenv()
    conn = db.client()
    now = datetime.now(timezone.utc)

    closes_dated = data.get_daily_closes(MAX_WARMUP + 10)
    bar_date, price = closes_dated[-1]
    closes = [c for _, c in closes_dated]
    run_date = bar_date

    # --- baseline first (agents' reviews compare against it) ---
    b_state = db.get_state(conn, BASELINE_KEY)
    b_port = db.portfolio_from_state(b_state)
    if b_port.position == "flat" and db.prev_equity(conn, BASELINE_KEY) is None:
        b_port, b_fill = ledger.buy(b_port, price)
        db.log_event(conn, "baseline_entry", f"bought {b_fill['qty']:.8f} @ {price:.2f}")
    b_port, b_eq, b_dd = ledger.mark(b_port, price)
    db.save_portfolio(conn, BASELINE_KEY, b_port)
    db.log_equity(conn, run_date, BASELINE_KEY, b_eq, b_dd, b_port.position)

    # --- each monster ---
    summary = []
    for strat in AGENTS.values():
        if db.decision_exists(conn, run_date, strat.key):
            summary.append(f"{strat.name}: already decided — no-op")
            continue

        state = db.get_state(conn, strat.key)
        port = db.portfolio_from_state(state)
        res = strat.evaluate(closes, port.position)

        prev_eq = db.prev_equity(conn, strat.key) or float(state["starting_capital"])
        halted = state["halted_until"] is not None and datetime.fromisoformat(
            state["halted_until"].replace("Z", "+00:00")
        ) > now
        gate = risk.gate(
            signal=res.signal,
            equity=port.equity(price),
            prev_equity=prev_eq,
            starting_capital=float(state["starting_capital"]),
            kill_switch_already_tripped=bool(state["kill_switch_tripped"]),
            halted=halted,
        )

        state_extra: dict = {}
        if gate.trip_kill_switch:
            state_extra["kill_switch_tripped"] = True
            db.log_event(conn, "kill_switch", f"{strat.key}: {gate.block_reason}")
        if gate.trip_daily_halt:
            state_extra["halted_until"] = (now + timedelta(hours=24)).isoformat()
            db.log_event(conn, "daily_halt", f"{strat.key}: {gate.block_reason}")

        action = "no-change"
        if res.signal in ("buy", "sell") and gate.approved:
            eq_before = port.equity(price)
            if res.signal == "buy":
                port, fill = ledger.buy(port, price)
            else:
                port, fill = ledger.sell_all(port, price)
            order_id = None
            if EXECUTE_ORDERS and strat.key == "kepler":
                order_id = broker.place_market_order(fill["side"], fill["qty"])
            db.log_trade(conn, {
                "agent": strat.key,
                "strategy_version": f"{STRATEGY_VERSION}/{strat.key}",
                "symbol": SYMBOL,
                "side": fill["side"],
                "qty": fill["qty"],
                "price": fill["price"],
                "fee_paid": fill["fee_paid"],
                "account_value_before": eq_before,
                "account_value_after": port.equity(price),
                "rationale": f"{res.indicators} -> {res.signal}; alpaca_order={order_id}",
            })
            action = "executed" if order_id else "simulated"
        elif res.signal in ("buy", "sell"):
            action = "blocked"

        db.log_decision(conn, {
            "run_date": run_date.isoformat(),
            "agent": strat.key,
            "strategy_version": f"{STRATEGY_VERSION}/{strat.key}",
            "price": price,
            "indicators": res.indicators,
            "in_neutral_zone": res.in_neutral_zone,
            "signal": res.signal,
            "position_before": state["position"],
            "action_taken": action,
            "block_reason": gate.block_reason,
        })

        port, eq, dd = ledger.mark(port, price)
        db.save_portfolio(conn, strat.key, port, **state_extra)
        db.log_equity(conn, run_date, strat.key, eq, dd, port.position)

        rules_followed = not (res.signal in ("buy", "sell") and not gate.approved
                              and action in ("executed", "simulated"))
        review.write_review(conn, run_date, strat.key, eq, b_eq, rules_followed,
                            gate.block_reason or "")
        summary.append(f"{strat.name}: {res.signal}/{action} eq={eq:,.0f}")

    print(f"{run_date} price={price:,.2f} baseline={b_eq:,.0f} | " + " | ".join(summary))


if __name__ == "__main__":
    run()
