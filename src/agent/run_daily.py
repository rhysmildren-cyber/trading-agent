"""The daily loop: core swarm (BTC + ETH divisions) plus the Degen Wing.

For each core agent: evaluate -> risk gate -> ledger op -> log. One baseline
per market. Degen agents use the leverage/short mechanics in degen.py, skip
the kill-switch gate (dying is their job), and stay dead once liquidated.

Idempotent per (bar date, agent). Only KEPLER (BTC) places ceremonial Alpaca
paper orders, and only with --execute.
"""

import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from agent import broker, data, db, degen, ledger, review, risk
from agent.config import STARTING_CAPITAL, STRATEGY_VERSION
from agent.strategies import AGENTS, BASELINES, DEGEN, MARKET_SYMBOLS, MAX_WARMUP

EXECUTE_ORDERS = "--execute" in sys.argv


def _run_baseline(conn, market, run_date, price):
    key = BASELINES[market]
    state = db.get_state(conn, key)
    port = db.portfolio_from_state(state)
    if port.position == "flat" and db.prev_equity(conn, key) is None:
        port, fill = ledger.buy(port, price)
        db.log_event(conn, "baseline_entry", f"{key}: bought {fill['qty']:.8f} @ {price:.2f}")
    port, eq, dd = ledger.mark(port, price)
    db.save_portfolio(conn, key, port)
    db.log_equity(conn, run_date, key, eq, dd, port.position)
    return eq


def _run_core_agent(conn, strat, closes, run_date, price, b_eq, now):
    state = db.get_state(conn, strat.key)
    port = db.portfolio_from_state(state)
    res = strat.evaluate(closes, port.position)

    prev_eq = db.prev_equity(conn, strat.key) or float(state["starting_capital"])
    halted = state["halted_until"] is not None and datetime.fromisoformat(
        state["halted_until"].replace("Z", "+00:00")) > now
    gate = risk.gate(
        signal=res.signal, equity=port.equity(price), prev_equity=prev_eq,
        starting_capital=float(state["starting_capital"]),
        kill_switch_already_tripped=bool(state["kill_switch_tripped"]), halted=halted)

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
        port, fill = (ledger.buy if res.signal == "buy" else ledger.sell_all)(port, price)
        order_id = None
        if EXECUTE_ORDERS and strat.key == "kepler":
            order_id = broker.place_market_order(fill["side"], fill["qty"])
        db.log_trade(conn, {
            "agent": strat.key, "strategy_version": f"{STRATEGY_VERSION}/{strat.key}",
            "symbol": strat.symbol, "side": fill["side"], "qty": fill["qty"],
            "price": fill["price"], "fee_paid": fill["fee_paid"],
            "account_value_before": eq_before, "account_value_after": port.equity(price),
            "rationale": f"{res.indicators} -> {res.signal}; alpaca_order={order_id}",
        })
        action = "executed" if order_id else "simulated"
    elif res.signal in ("buy", "sell"):
        action = "blocked"

    db.log_decision(conn, {
        "run_date": run_date.isoformat(), "agent": strat.key,
        "strategy_version": f"{STRATEGY_VERSION}/{strat.key}", "price": price,
        "indicators": res.indicators, "in_neutral_zone": res.in_neutral_zone,
        "signal": res.signal, "position_before": state["position"],
        "action_taken": action, "block_reason": gate.block_reason,
    })

    port, eq, dd = ledger.mark(port, price)
    db.save_portfolio(conn, strat.key, port, **state_extra)
    db.log_equity(conn, run_date, strat.key, eq, dd, port.position)
    review.write_review(conn, run_date, strat.key, eq, b_eq, True, gate.block_reason or "")
    return f"{strat.name}: {res.signal}/{action} eq={eq:,.0f}"


def _run_degen_agent(conn, strat, closes, run_date, price, prev_price):
    state = db.get_state(conn, strat.key)
    equity = float(state["cash"])
    qty = float(state["qty"])
    position = state["position"]
    liquidated = bool(state["kill_switch_tripped"])  # repurposed: stays dead

    if liquidated:
        db.log_decision(conn, {
            "run_date": run_date.isoformat(), "agent": strat.key,
            "strategy_version": f"{STRATEGY_VERSION}/{strat.key}", "price": price,
            "indicators": {}, "in_neutral_zone": False, "signal": "hold",
            "position_before": position, "action_taken": "no-change",
            "block_reason": "liquidated: permanently out of the game",
        })
        db.log_equity(conn, run_date, strat.key, equity, 1.0, "flat")
        return f"{strat.name}: LIQUIDATED eq={equity:,.0f}"

    # mark yesterday's position to today's price (funding included)
    equity = degen.mark(equity, qty, price, prev_price)
    entry_equity = float(state["entry_equity"] or 0)

    action, block_reason, extra = "no-change", None, {}
    res = strat.evaluate(closes, position)

    if qty != 0 and degen.is_liquidated(equity, entry_equity):
        equity = degen.liquidate(equity)
        qty, position = 0.0, "flat"
        action, block_reason = "liquidated", "margin call: position force-closed"
        extra = {"kill_switch_tripped": True, "entry_equity": None, "entry_price": None}
        db.log_event(conn, "liquidation",
                     f"{strat.key}: wiped out; ${equity:,.0f} of scraps remain")
    elif res.signal == "buy" and position == "flat":
        eq_before = equity
        equity, qty, fill = degen.open_position(equity, price, strat.leverage, strat.direction)
        position = "long" if strat.direction == 1 else "short"
        extra = {"entry_equity": eq_before, "entry_price": price}
        db.log_trade(conn, {
            "agent": strat.key, "strategy_version": f"{STRATEGY_VERSION}/{strat.key}",
            "symbol": strat.symbol, "side": "buy", "qty": abs(fill.qty), "price": price,
            "fee_paid": fill.fee_paid, "account_value_before": eq_before,
            "account_value_after": equity,
            "rationale": f"{res.indicators} -> open {position} {strat.leverage:g}x "
                         f"(notional ${fill.notional:,.0f})",
        })
        action = "simulated"
    elif res.signal == "sell" and position in ("long", "short"):
        eq_before = equity
        equity, fill = degen.close_position(equity, qty, price)
        qty, position = 0.0, "flat"
        extra = {"entry_equity": None, "entry_price": None}
        db.log_trade(conn, {
            "agent": strat.key, "strategy_version": f"{STRATEGY_VERSION}/{strat.key}",
            "symbol": strat.symbol, "side": "sell", "qty": abs(fill.qty), "price": price,
            "fee_paid": fill.fee_paid, "account_value_before": eq_before,
            "account_value_after": equity,
            "rationale": f"{res.indicators} -> close position",
        })
        action = "simulated"

    db.log_decision(conn, {
        "run_date": run_date.isoformat(), "agent": strat.key,
        "strategy_version": f"{STRATEGY_VERSION}/{strat.key}", "price": price,
        "indicators": res.indicators, "in_neutral_zone": res.in_neutral_zone,
        "signal": res.signal, "position_before": state["position"],
        "action_taken": action, "block_reason": block_reason,
    })
    peak = max(float(state["peak_equity"]), equity)
    dd = 0.0 if peak <= 0 else (peak - equity) / peak
    conn.table("system_state").update({
        "position": position, "qty": qty, "cash": equity, "peak_equity": peak, **extra,
    }).eq("agent", strat.key).execute()
    db.log_equity(conn, run_date, strat.key, equity, dd, position)
    return f"{strat.name}: {res.signal}/{action} eq={equity:,.0f}"


def run() -> None:
    load_dotenv()
    conn = db.client()
    now = datetime.now(timezone.utc)

    market_closes = {m: data.get_daily_closes(MAX_WARMUP + 10, sym)
                     for m, sym in MARKET_SYMBOLS.items()}
    run_date = market_closes["BTC"][-1][0]
    summary = []

    b_eqs = {m: _run_baseline(conn, m, run_date, closes[-1][1])
             for m, closes in market_closes.items()}

    for strat in AGENTS.values():
        closes_dated = market_closes[strat.market]
        if db.decision_exists(conn, run_date, strat.key):
            summary.append(f"{strat.name}: no-op")
            continue
        summary.append(_run_core_agent(
            conn, strat, [c for _, c in closes_dated], run_date,
            closes_dated[-1][1], b_eqs[strat.market], now))

    for strat in DEGEN.values():
        closes_dated = market_closes[strat.market]
        if db.decision_exists(conn, run_date, strat.key):
            summary.append(f"{strat.name}: no-op")
            continue
        prices = [c for _, c in closes_dated]
        summary.append(_run_degen_agent(
            conn, strat, prices, run_date, prices[-1], prices[-2]))

    print(f"{run_date} | " + " | ".join(summary))


if __name__ == "__main__":
    run()
