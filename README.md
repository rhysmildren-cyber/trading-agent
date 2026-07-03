# Autonomous Trend Agent (v1.0-sma50)

Paper-trading BTC trend follower: long when price closes >1% above the 50-day
SMA, flat when >1% below, hold inside the band. Every trade pays 0.25% fee +
0.10% slippage in a simulated ledger (the source of truth for equity), and is
measured daily against a buy-and-hold baseline paying the same costs.
Paper only — no real money. See the PRD and plan for full rules.

## Status / runbook

- **Backtest (validation):** `python -m agent.backtest 3`
- **Daily loop (signal-only):** `python -m agent.run_daily`
- **Daily loop (places paper orders):** `python -m agent.run_daily --execute`
  — do not enable until step 7 sign-off; then also add `--execute` in
  `.github/workflows/daily.yml`.
- **Tests:** `pytest`

Idempotent per UTC bar date: re-running on the same day no-ops.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env   # then fill in the four values below
```

| Var | Where to get it |
|---|---|
| `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` | alpaca.markets → paper account → API keys (PAPER keys only) |
| `SUPABASE_URL` | `https://vpzozalrecmncjpnnpkp.supabase.co` (project: trading-agent) |
| `SUPABASE_SERVICE_KEY` | Supabase dashboard → project settings → API → service_role key |

For the scheduler: create a private GitHub repo, push, and add the same four
values as Actions secrets. The workflow (`.github/workflows/daily.yml`) runs at
00:05 UTC daily and can be triggered manually via workflow_dispatch.

## Hard rules (do not edit casually)

All parameters live in `src/agent/config.py`. Changing any of them is a new
`STRATEGY_VERSION` — log it, don't drift. The risk gate (`risk.py`) blocks
trading on: kill-switch (equity < 75% of starting capital, requires manually
setting `system_state.kill_switch_tripped = false` to resume) and daily halt
(>10% single-day loss pauses 24h).

## Kill-switch recovery (manual review)

```sql
-- after reviewing why it tripped:
update system_state set kill_switch_tripped = false where system = 'strategy';
```
