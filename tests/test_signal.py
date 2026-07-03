import pytest

from agent.signal import compute_sma, evaluate


def test_sma():
    assert compute_sma([1.0] * 50) == 1.0
    assert compute_sma(list(range(100)), window=50) == sum(range(50, 100)) / 50


def test_sma_requires_window():
    with pytest.raises(ValueError):
        compute_sma([1.0] * 49)


def test_buy_above_band_when_flat():
    r = evaluate(price=102.0, sma=100.0, position="flat")
    assert r.signal == "buy" and not r.in_deadband


def test_sell_below_band_when_long():
    r = evaluate(price=98.0, sma=100.0, position="long")
    assert r.signal == "sell" and not r.in_deadband


def test_deadband_holds_current_state_both_ways():
    # price 0.5% above SMA: inside the 1% band -> hold whatever we are
    assert evaluate(100.5, 100.0, "flat").signal == "hold"
    assert evaluate(100.5, 100.0, "long").signal == "hold"
    # price 0.5% below SMA: still inside band
    assert evaluate(99.5, 100.0, "long").signal == "hold"
    assert evaluate(99.5, 100.0, "flat").signal == "hold"


def test_no_double_entry_or_exit():
    # already long, price above band -> hold (not buy again)
    assert evaluate(102.0, 100.0, "long").signal == "hold"
    # already flat, price below band -> hold (no shorting)
    assert evaluate(98.0, 100.0, "flat").signal == "hold"


def test_hysteresis_prevents_whipsaw():
    # long at SMA cross: price oscillating within +/-1% never flips state
    position = "long"
    for price in [100.9, 99.2, 100.5, 99.1]:
        assert evaluate(price, 100.0, position).signal == "hold"
