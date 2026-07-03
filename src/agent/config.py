"""All pinned parameters for v1. Changing any of these is a new strategy version."""

STRATEGY_VERSION = "v1.0-sma50"
SYMBOL = "BTC/USD"
AGENT_NAME = "KEPLER"

# Signal
SMA_WINDOW = 50          # days
DEADBAND = 0.01          # 1% above/below SMA required to switch state

# Cost model (per side, applied to notional)
FEE_RATE = 0.0025        # 0.25% — high end of Alpaca crypto fees
SLIPPAGE_RATE = 0.0010   # 0.10% adverse slippage assumption
COST_RATE = FEE_RATE + SLIPPAGE_RATE

# Risk rules
DEPLOY_FRACTION = 0.95       # never deploy more than 95% of account value
KILL_SWITCH_DRAWDOWN = 0.25  # halt permanently if equity < 75% of starting capital
DAILY_LOSS_HALT = 0.10       # pause 24h if a single day loses > 10%

# Capital (simulated ledger; both systems start identical)
STARTING_CAPITAL = 100_000.0

SYSTEM_STRATEGY = "strategy"
SYSTEM_BASELINE = "baseline"
