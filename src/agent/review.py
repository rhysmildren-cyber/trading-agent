"""Daily review row: judges process first, profit second."""

from datetime import date

from supabase import Client


def write_daily_review(db: Client, day: date, rules_followed: bool, notes: str = "") -> dict | None:
    rows = (
        db.table("equity_daily").select("system,equity")
        .eq("date", day.isoformat()).execute().data
    )
    eq = {r["system"]: float(r["equity"]) for r in rows}
    if "strategy" not in eq or "baseline" not in eq:
        return None
    row = {
        "date": day.isoformat(),
        "strategy_equity": eq["strategy"],
        "baseline_equity": eq["baseline"],
        "delta": eq["strategy"] - eq["baseline"],
        "rules_followed": rules_followed,
        "notes": notes,
    }
    db.table("daily_review").upsert(row, on_conflict="date").execute()
    return row
