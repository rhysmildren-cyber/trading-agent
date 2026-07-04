import pytest

from agent.signal import rsi_wilder
from agent.strategies import AGENTS


def closes_trending(n, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


# --- VECTOR (momentum) ---

def test_vector_buys_positive_momentum_when_flat():
    r = AGENTS["vector"].evaluate(closes_trending(60, step=1.0), "flat")
    assert r.signal == "buy" and r.indicators["roc_30"] > 0


def test_vector_sells_negative_momentum_when_long():
    r = AGENTS["vector"].evaluate(closes_trending(60, step=-1.0), "long")
    assert r.signal == "sell"


def test_vector_holds_when_already_positioned_right():
    assert AGENTS["vector"].evaluate(closes_trending(60, step=1.0), "long").signal == "hold"
    assert AGENTS["vector"].evaluate(closes_trending(60, step=-1.0), "flat").signal == "hold"


# --- DONNIE (breakout) ---

def test_donnie_buys_20day_high_when_flat():
    closes = [100.0] * 40 + [101.0]  # new high above the flat 20-day range
    r = AGENTS["donnie"].evaluate(closes, "flat")
    assert r.signal == "buy" and r.indicators["high_20"] == 100.0


def test_donnie_exits_10day_low_when_long():
    closes = [100.0] * 40 + [99.0]
    r = AGENTS["donnie"].evaluate(closes, "long")
    assert r.signal == "sell" and r.indicators["low_10"] == 100.0


def test_donnie_holds_inside_channel():
    closes = [100.0, 110.0] * 20 + [105.0]  # inside the 100-110 channel
    assert AGENTS["donnie"].evaluate(closes, "flat").signal == "hold"
    assert AGENTS["donnie"].evaluate(closes, "long").signal == "hold"
    assert AGENTS["donnie"].evaluate(closes, "flat").in_neutral_zone


# --- DIP (RSI mean reversion) ---

def test_rsi_extremes():
    assert rsi_wilder(closes_trending(60, step=1.0)) == 100.0
    assert rsi_wilder(closes_trending(60, start=200.0, step=-1.0)) < 5.0


def test_rsi_requires_history():
    with pytest.raises(ValueError):
        rsi_wilder([100.0] * 10, period=14)


def test_dip_buys_panic_when_flat():
    r = AGENTS["dip"].evaluate(closes_trending(60, start=200.0, step=-1.0), "flat")
    assert r.signal == "buy" and r.indicators["rsi_14"] < 30


def test_dip_sells_relief_when_long():
    closes = closes_trending(30, start=100.0, step=-1.0) + closes_trending(30, start=71.0, step=2.0)
    r = AGENTS["dip"].evaluate(closes, "long")
    assert r.signal == "sell" and r.indicators["rsi_14"] > 60


def test_dip_neutral_zone_holds():
    # alternating small moves keep RSI mid-range
    closes = [100.0 + (0.5 if i % 2 else -0.5) for i in range(60)]
    r = AGENTS["dip"].evaluate(closes, "flat")
    assert r.signal == "hold" and r.in_neutral_zone


# --- KEPLER via registry matches the original signal path ---

def test_kepler_registry_regression():
    up = closes_trending(60, start=100.0, step=1.0)   # price well above sma
    assert AGENTS["kepler"].evaluate(up, "flat").signal == "buy"
    down = closes_trending(60, start=200.0, step=-1.0)
    assert AGENTS["kepler"].evaluate(down, "long").signal == "sell"


def test_registry_metadata_complete():
    for s in AGENTS.values():
        assert s.warmup > 0 and s.rule and s.belief and s.flat_text and s.long_text
