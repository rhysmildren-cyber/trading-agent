"""All pinned parameters for v1. Changing any of these is a new strategy version."""

STRATEGY_VERSION = "v2.0-swarm"
SYMBOL = "BTC/USD"

# Signal parameters — pre-registered textbook defaults. Changing any of these
# after swarm launch invalidates the experiment; don't.
SMA_WINDOW = 50          # KEPLER: days
DEADBAND = 0.01          # KEPLER: 1% above/below SMA required to switch state
MOM_WINDOW = 30          # VECTOR: trailing return lookback
BREAKOUT_ENTRY = 20      # DONNIE: buy on N-day-high close
BREAKOUT_EXIT = 10       # DONNIE: exit on N-day-low close
RSI_PERIOD = 14          # DIP: Wilder RSI period
RSI_BUY = 30             # DIP: buy below
RSI_SELL = 60            # DIP: sell above

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
