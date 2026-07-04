"""The monster roster: one pre-registered strategy per agent.

Every strategy is a pure function over daily closes. Parameters live in
config.py and are frozen for the life of the experiment — no tuning after
launch. Adding an agent means adding an entry here; everything else
(engine, backtest, dashboard) iterates the registry.
"""

from dataclasses import dataclass, field
from typing import Callable

from agent import signal
from agent.config import (
    BREAKOUT_ENTRY, BREAKOUT_EXIT, DEADBAND, MOM_WINDOW,
    RSI_BUY, RSI_PERIOD, RSI_SELL, SMA_WINDOW,
)


@dataclass(frozen=True)
class StrategyResult:
    signal: str                 # "buy" | "sell" | "hold"
    indicators: dict            # what it saw, for the decision log
    in_neutral_zone: bool       # inside the rule's no-trade region


@dataclass(frozen=True)
class Strategy:
    key: str                    # db identifier
    name: str                   # display name
    color: str                  # body hue (base, dark) for the character rig
    color_dark: str
    accessory: str              # character variant: horns/antenna/shell/droop
    rule: str                   # plain-english rule, one line
    belief: str                 # the market belief being tested
    warmup: int                 # bars needed before first evaluation
    evaluate: Callable[[list[float], str], StrategyResult]
    flat_text: str = ""         # plain-english "why I'm in cash"
    long_text: str = ""         # plain-english "why I'm holding"
    # pre-registered 3y backtest (2023-07-05 -> 2026-07-03), recorded at launch;
    # used by the dashboard to compare live results against expectations
    expectation: dict = field(default_factory=dict)


def _kepler(closes: list[float], position: str) -> StrategyResult:
    price = closes[-1]
    sma = signal.compute_sma(closes)
    r = signal.evaluate(price, sma, position, DEADBAND)
    return StrategyResult(r.signal, {"sma_50": round(sma, 2)}, r.in_deadband)


def _vector(closes: list[float], position: str) -> StrategyResult:
    roc = closes[-1] / closes[-(MOM_WINDOW + 1)] - 1
    if roc > 0 and position == "flat":
        sig = "buy"
    elif roc <= 0 and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    return StrategyResult(sig, {"roc_30": round(roc, 4)}, False)


def _donnie(closes: list[float], position: str) -> StrategyResult:
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


def _dip(closes: list[float], position: str) -> StrategyResult:
    rsi = signal.rsi_wilder(closes, RSI_PERIOD)
    if rsi < RSI_BUY and position == "flat":
        sig = "buy"
    elif rsi > RSI_SELL and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    return StrategyResult(sig, {"rsi_14": round(rsi, 1)}, RSI_BUY <= rsi <= RSI_SELL)


AGENTS: dict[str, Strategy] = {s.key: s for s in [
    Strategy(
        key="kepler", name="KEPLER", color="#66ad64", color_dark="#2d5a38",
        accessory="horns",
        rule=f"Long above the {SMA_WINDOW}-day average (±{DEADBAND:.0%} buffer), cash below",
        belief="Trends persist",
        warmup=SMA_WINDOW, evaluate=_kepler,
        flat_text="Price is below the 50-day trend line, so I'm parked in cash until it climbs back above.",
        long_text="Price is above the 50-day trend line, so I stay in Bitcoin.",
        expectation={"ret": 1.408, "dd": 0.307, "sharpe": 1.08, "trades_yr": 12},
    ),
    Strategy(
        key="vector", name="VECTOR", color="#e8923a", color_dark="#8a4f1d",
        accessory="antenna",
        rule=f"Long while the last {MOM_WINDOW} days are net positive, cash when negative",
        belief="Winners keep winning",
        warmup=MOM_WINDOW + 1, evaluate=_vector,
        flat_text="The last 30 days are net negative, so momentum says stay in cash.",
        long_text="The last 30 days are net positive — momentum says keep riding.",
        expectation={"ret": 0.347, "dd": 0.399, "sharpe": 0.47, "trades_yr": 35},
    ),
    Strategy(
        key="donnie", name="DONNIE", color="#3aaea0", color_dark="#1d5f58",
        accessory="shell",
        rule=f"Buy a {BREAKOUT_ENTRY}-day-high close, exit on a {BREAKOUT_EXIT}-day low",
        belief="New highs beget new highs",
        warmup=BREAKOUT_ENTRY + 1, evaluate=_donnie,
        flat_text="No fresh 20-day high yet. I only move on a breakout — slow is smooth.",
        long_text="Bought the breakout; I'll crawl back to cash if price hits a 10-day low.",
        expectation={"ret": 1.160, "dd": 0.304, "sharpe": 1.07, "trades_yr": 14},
    ),
    Strategy(
        key="dip", name="DIP", color="#9a7be0", color_dark="#4f3a8a",
        accessory="droop",
        rule=f"Buy panic (RSI below {RSI_BUY}), sell relief (RSI above {RSI_SELL})",
        belief="Panic overshoots — the anti-trend control",
        warmup=50, evaluate=_dip,  # extra bars so Wilder smoothing stabilizes
        flat_text="Nobody's panicking — RSI is calm, so there's nothing cheap to buy.",
        long_text="Bought someone's panic. Now waiting for the relief rally to sell into.",
        expectation={"ret": 0.197, "dd": 0.194, "sharpe": 0.36, "trades_yr": 4},
    ),
]}

BASELINE_KEY = "baseline"
MAX_WARMUP = max(s.warmup for s in AGENTS.values())
