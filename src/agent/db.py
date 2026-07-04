"""Supabase persistence, keyed by agent. All writes idempotent per UTC date."""

import os
from datetime import date

from supabase import Client, create_client

from agent.config import STARTING_CAPITAL
from agent.ledger import Portfolio


def client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# --- system_state ---

def get_state(db: Client, agent: str) -> dict:
    rows = db.table("system_state").select("*").eq("agent", agent).execute().data
    if rows:
        return rows[0]
    row = {
        "agent": agent,
        "position": "flat",
        "qty": 0,
        "cash": STARTING_CAPITAL,
        "peak_equity": STARTING_CAPITAL,
        "starting_capital": STARTING_CAPITAL,
        "kill_switch_tripped": False,
        "halted_until": None,
        "entry_equity": None,
        "entry_price": None,
    }
    db.table("system_state").insert(row).execute()
    return row


def save_portfolio(db: Client, agent: str, p: Portfolio, **extra) -> None:
    db.table("system_state").update(
        {"position": p.position, "qty": p.qty, "cash": p.cash, "peak_equity": p.peak_equity, **extra}
    ).eq("agent", agent).execute()


def portfolio_from_state(state: dict) -> Portfolio:
    return Portfolio(
        cash=float(state["cash"]),
        qty=float(state["qty"]),
        peak_equity=float(state["peak_equity"]),
    )


# --- logging tables ---

def decision_exists(db: Client, run_date: date, agent: str) -> bool:
    rows = (db.table("decisions").select("id")
            .eq("run_date", run_date.isoformat()).eq("agent", agent).execute().data)
    return len(rows) > 0


def log_decision(db: Client, row: dict) -> None:
    db.table("decisions").insert(row).execute()


def log_trade(db: Client, row: dict) -> None:
    db.table("trades").insert(row).execute()


def log_equity(db: Client, day: date, agent: str, equity: float, drawdown_pct: float, position: str) -> None:
    db.table("equity_daily").upsert(
        {"date": day.isoformat(), "agent": agent, "equity": equity,
         "drawdown_pct": drawdown_pct, "position": position},
        on_conflict="date,agent",
    ).execute()


def log_event(db: Client, kind: str, detail: str) -> None:
    db.table("events").insert({"kind": kind, "detail": detail}).execute()


def log_review(db: Client, row: dict) -> None:
    db.table("daily_review").upsert(row, on_conflict="date,agent").execute()


def prev_equity(db: Client, agent: str) -> float | None:
    rows = (
        db.table("equity_daily").select("equity").eq("agent", agent)
        .order("date", desc=True).limit(1).execute().data
    )
    return float(rows[0]["equity"]) if rows else None
