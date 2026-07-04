# The Swarm (v2.0)

Four paper-trading agents, each running one pre-registered rule on BTC/USD
daily closes, all racing a buy-and-hold baseline with identical costs (0.25%
fee + 0.10% slippage per side) and identical risk rails. HOUSTON, the
overseer, keeps score and never trades. Simulated ledgers in Supabase are the
source of truth. Paper only — no real money.

**Dashboard:** https://rhysmildren-cyber.github.io/trading-agent/

## The roster — rules locked at launch (2026-07-04), never tuned

| Agent | Rule | 3y backtest (pre-registered expectation) |
|---|---|---|
| KEPLER | Long > SMA-50 × 1.01, flat < × 0.99 | +140.8%, 30.7% maxDD, Sharpe 1.08, 36 trades |
| VECTOR | Long if 30-day return > 0, else cash | +34.7%, 39.9% maxDD, Sharpe 0.47, 104 trades |
| DONNIE | Buy 20-day-high close, exit 10-day low | +116.0%, 30.4% maxDD, Sharpe 1.07, 42 trades |
| DIP | Buy RSI-14 < 30, sell RSI-14 > 60 | +19.7%, 19.4% maxDD, Sharpe 0.36, 13 trades |
| baseline | Buy day one, never sell | +99.1%, 52.4% maxDD, Sharpe 0.73 |

(Backtest 2023-07-05 → 2026-07-03, all costs applied. These numbers exist to
catch bugs and anchor expectations — not as promises. With four racers the
live leader is partly luck; judgement happens at day 90 against the baseline
and these expectations, not the leaderboard.)

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

All parameters live in `src/agent/config.py`; strategies in
`src/agent/strategies.py`. Changing any parameter after launch invalidates the
experiment — a change means a new `STRATEGY_VERSION` and a restarted clock.
The risk gate (`risk.py`) applies to every agent independently: kill-switch
(equity < 75% of starting capital) and daily halt (>10% single-day loss
pauses 24h). The overseer never allocates capital between agents.

## Kill-switch recovery (manual review)

```sql
-- after reviewing why it tripped:
update system_state set kill_switch_tripped = false where agent = 'kepler';
```
