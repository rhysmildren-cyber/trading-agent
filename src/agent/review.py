"""Daily review rows: one per agent per day — process first, profit second."""

from datetime import date

from supabase import Client


def write_review(db: Client, day: date, agent: str, equity: float,
                 baseline_equity: float, rules_followed: bool, notes: str = "") -> dict:
    row = {
        "date": day.isoformat(),
        "agent": agent,
        "equity": equity,
        "delta_vs_baseline": equity - baseline_equity,
        "rules_followed": rules_followed,
        "notes": notes,
    }
    db.table("daily_review").upsert(row, on_conflict="date,agent").execute()
    return row
