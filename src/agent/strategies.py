"""The monster roster: one pre-registered strategy per agent.

Every strategy is a pure function over daily closes. Parameters live in
config.py and are frozen for the life of the experiment — no tuning after
launch. Adding an agent means adding an entry here; everything else
(engine, backtest, lab, dashboard) iterates the registries.

Three registries:
  AGENTS       — the core experiment: 4 rules × 2 markets (BTC, ETH)
  DEGEN        — the quarantined experimental wing (leverage, shorting);
                 excluded from HOUSTON's judgement, allowed to blow up
  BASE         — the 4 underlying rules, market-agnostic (used by lab/backtest)
"""

from dataclasses import dataclass, field, replace
from typing import Callable

from agent import signal
from agent.config import (
    BREAKOUT_ENTRY, BREAKOUT_EXIT, DEADBAND, MOM_WINDOW,
    RSI_BUY, RSI_PERIOD, RSI_SELL, SMA_WINDOW,
)


@dataclass(frozen=True)
class StrategyResult:
    signal: str                 # "buy" | "sell" | "hold"  (buy = open, sell = close)
    indicators: dict            # what it saw, for the decision log
    in_neutral_zone: bool       # inside the rule's no-trade region


@dataclass(frozen=True)
class Strategy:
    key: str                    # db identifier
    base: str                   # underlying rule family (kepler/vector/donnie/dip)
    name: str                   # display name
    color: str
    color_dark: str
    accessory: str              # character variant: horns/antenna/shell/droop/headset
    rule: str
    belief: str
    warmup: int
    evaluate: Callable[[list[float], str], StrategyResult]
    market: str = "BTC"
    symbol: str = "BTC/USD"
    flat_text: str = ""
    long_text: str = ""
    expectation: dict = field(default_factory=dict)
    # degen wing only
    degen: bool = False
    leverage: float = 1.0
    direction: int = 1          # 1 = long the signal, -1 = short it


def _kepler(closes, position):
    price = closes[-1]
    sma = signal.compute_sma(closes)
    r = signal.evaluate(price, sma, position if position in ("flat", "long") else "long", DEADBAND)
    return StrategyResult(r.signal, {"sma_50": round(sma, 2)}, r.in_deadband)


def _vector(closes, position):
    roc = closes[-1] / closes[-(MOM_WINDOW + 1)] - 1
    if roc > 0 and position == "flat":
        sig = "buy"
    elif roc <= 0 and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    return StrategyResult(sig, {"roc_30": round(roc, 4)}, False)


def _donnie(closes, position):
    price = closes[-1]
    entry_high = max(closes[-(BREAKOUT_ENTRY + 1):-1])
    exit_low = min(closes[-(BREAKOUT_EXIT + 1):-1])
    if price >= entry_high and position == "flat":
        sig = "buy"
    elif price <= exit_low and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    neutral = not (price >= entry_high or price <= exit_low)
    return StrategyResult(
        sig, {"high_20": round(entry_high, 2), "low_10": round(exit_low, 2)}, neutral)


def _dip(closes, position):
    rsi = signal.rsi_wilder(closes, RSI_PERIOD)
    if rsi < RSI_BUY and position == "flat":
        sig = "buy"
    elif rsi > RSI_SELL and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    return StrategyResult(sig, {"rsi_14": round(rsi, 1)}, RSI_BUY <= rsi <= RSI_SELL)


def _grudge(closes, position):
    """Inverse KEPLER: short below the trend line, cover above it."""
    price = closes[-1]
    sma = signal.compute_sma(closes)
    upper, lower = sma * (1 + DEADBAND), sma * (1 - DEADBAND)
    if price < lower and position == "flat":
        sig = "buy"       # open the short
    elif price > upper and position == "short":
        sig = "sell"      # cover
    else:
        sig = "hold"
    return StrategyResult(sig, {"sma_50": round(sma, 2)}, lower <= price <= upper)


BASE: list[Strategy] = [
    Strategy(
        key="kepler", base="kepler", name="KEPLER", color="#66ad64", color_dark="#2d5a38",
        accessory="horns",
        rule=f"Long above the {SMA_WINDOW}-day average (±{DEADBAND:.0%} buffer), cash below",
        belief="Trends persist",
        warmup=SMA_WINDOW, evaluate=_kepler,
        flat_text="Price is below the 50-day trend line, so I'm parked in cash until it climbs back above.",
        long_text="Price is above the 50-day trend line, so I stay invested.",
        expectation={"ret": 1.408, "dd": 0.307, "sharpe": 1.08, "trades_yr": 12},
    ),
    Strategy(
        key="vector", base="vector", name="VECTOR", color="#e8923a", color_dark="#8a4f1d",
        accessory="antenna",
        rule=f"Long while the last {MOM_WINDOW} days are net positive, cash when negative",
        belief="Winners keep winning",
        warmup=MOM_WINDOW + 1, evaluate=_vector,
        flat_text="The last 30 days are net negative, so momentum says stay in cash.",
        long_text="The last 30 days are net positive — momentum says keep riding.",
        expectation={"ret": 0.347, "dd": 0.399, "sharpe": 0.47, "trades_yr": 35},
    ),
    Strategy(
        key="donnie", base="donnie", name="DONNIE", color="#3aaea0", color_dark="#1d5f58",
        accessory="shell",
        rule=f"Buy a {BREAKOUT_ENTRY}-day-high close, exit on a {BREAKOUT_EXIT}-day low",
        belief="New highs beget new highs",
        warmup=BREAKOUT_ENTRY + 1, evaluate=_donnie,
        flat_text="No fresh 20-day high yet. I only move on a breakout — slow is smooth.",
        long_text="Bought the breakout; I'll crawl back to cash if price hits a 10-day low.",
        expectation={"ret": 1.160, "dd": 0.304, "sharpe": 1.07, "trades_yr": 14},
    ),
    Strategy(
        key="dip", base="dip", name="DIP", color="#9a7be0", color_dark="#4f3a8a",
        accessory="droop",
        rule=f"Buy panic (RSI below {RSI_BUY}), sell relief (RSI above {RSI_SELL})",
        belief="Panic overshoots — the anti-trend control",
        warmup=50, evaluate=_dip,  # extra bars so Wilder smoothing stabilizes
        flat_text="Nobody's panicking — RSI is calm, so there's nothing cheap to buy.",
        long_text="Bought someone's panic. Now waiting for the relief rally to sell into.",
        expectation={"ret": 0.197, "dd": 0.194, "sharpe": 0.36, "trades_yr": 4},
    ),
]

# ETH mirror: identical rules and parameters, second market, own baseline.
# Expectations recorded from the ETH backtest at launch (same 3y window).
ETH_EXPECTATIONS: dict[str, dict] = {
    "kepler": {"ret": 0.905, "dd": 0.469, "sharpe": 0.72, "trades_yr": 12},
    "vector": {"ret": 0.787, "dd": 0.445, "sharpe": 0.67, "trades_yr": 28},
    "donnie": {"ret": -0.158, "dd": 0.519, "sharpe": 0.02, "trades_yr": 16},
    "dip":    {"ret": -0.047, "dd": 0.397, "sharpe": 0.14, "trades_yr": 4},
}

AGENTS: dict[str, Strategy] = {s.key: s for s in BASE}
for s in BASE:
    AGENTS[f"{s.key}_eth"] = replace(
        s, key=f"{s.key}_eth", name=f"{s.name}·ETH", market="ETH", symbol="ETH/USD",
        flat_text=s.flat_text.replace("Bitcoin", "Ethereum"),
        long_text=s.long_text.replace("Bitcoin", "Ethereum"),
        expectation=ETH_EXPECTATIONS[s.key],
    )

# The Degen Wing: quarantined, excluded from HOUSTON's judgement, allowed to die.
DEGEN: dict[str, Strategy] = {s.key: s for s in [
    Strategy(
        key="spicy", base="kepler", name="SPICY", color="#ff6a3d", color_dark="#8a2f14",
        accessory="horns",
        rule="KEPLER's exact signal, but with 3× borrowed money",
        belief="Leverage just makes a good thing better (narrator: it doesn't)",
        warmup=SMA_WINDOW, evaluate=_kepler,
        degen=True, leverage=3.0, direction=1,
        flat_text="Below the trend line, flat — even I don't 3x a downtrend.",
        long_text="Above the trend line with 3× leverage. Every 1% move in Bitcoin is 3% to me, both directions.",
    ),
    Strategy(
        key="grudge", base="kepler", name="GRUDGE", color="#7d8fb3", color_dark="#38415a",
        accessory="droop",
        rule="Shorts below the trend line, covers above — profits only when BTC falls",
        belief="Everything is going to zero eventually",
        warmup=SMA_WINDOW, evaluate=_grudge,
        degen=True, leverage=1.0, direction=-1,
        flat_text="Price is above the trend line, so nothing to be angry about yet. Waiting.",
        long_text="Short below the trend line. I make money when Bitcoin falls and bleed when it rallies.",
    ),
]}

BASELINE_KEY = "baseline"
BASELINES = {"BTC": "baseline", "ETH": "baseline_eth"}
MARKET_SYMBOLS = {"BTC": "BTC/USD", "ETH": "ETH/USD"}
MAX_WARMUP = max(s.warmup for s in AGENTS.values())
