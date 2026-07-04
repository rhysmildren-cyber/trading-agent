import pytest

from agent import degen
from agent.config import COST_RATE, DEPLOY_FRACTION
from agent.strategies import DEGEN


def test_open_3x_long_pays_fees_on_full_notional():
    eq, qty, fill = degen.open_position(100_000, price=50_000, leverage=3, direction=1)
    assert fill.notional == pytest.approx(100_000 * DEPLOY_FRACTION * 3)
    assert fill.fee_paid == pytest.approx(fill.notional * COST_RATE)  # 3x the fees too
    assert qty == pytest.approx(fill.notional / 50_000)
    assert eq == pytest.approx(100_000 - fill.fee_paid)


def test_3x_long_amplifies_moves_both_ways():
    eq0, qty, _ = degen.open_position(100_000, 50_000, leverage=3, direction=1)
    up = degen.mark(eq0, qty, 55_000, 50_000)     # +10% price move
    down = degen.mark(eq0, qty, 45_000, 50_000)   # -10% price move
    assert (up - eq0) / 100_000 > 0.27            # ~ +28.5% equity (3x minus funding)
    assert (down - eq0) / 100_000 < -0.28


def test_short_profits_when_price_falls():
    eq0, qty, _ = degen.open_position(100_000, 50_000, leverage=1, direction=-1)
    assert qty < 0
    after = degen.mark(eq0, qty, 45_000, 50_000)
    assert after > eq0  # short gains on the drop


def test_liquidation_triggers_and_haircuts():
    eq0, qty, _ = degen.open_position(100_000, 50_000, leverage=3, direction=1)
    # a ~32% drop wipes ~96% of 3x equity
    wrecked = degen.mark(eq0, qty, 34_000, 50_000)
    assert degen.is_liquidated(wrecked, 100_000)
    assert degen.liquidate(wrecked) < wrecked
    assert degen.liquidate(-5.0) == 0.0  # never negative


def test_funding_bleeds_while_positioned():
    eq0, qty, _ = degen.open_position(100_000, 50_000, leverage=3, direction=1)
    flat_price = degen.mark(eq0, qty, 50_000, 50_000)
    assert flat_price < eq0  # price unchanged, funding still charged


def test_grudge_signals_inverse_kepler():
    up = [100.0 + i for i in range(60)]     # price far above sma
    down = [200.0 - i for i in range(60)]   # price far below sma
    g = DEGEN["grudge"]
    assert g.evaluate(down, "flat").signal == "buy"     # opens short in downtrend
    assert g.evaluate(up, "short").signal == "sell"     # covers in uptrend
    assert g.evaluate(up, "flat").signal == "hold"      # never long
    assert DEGEN["spicy"].leverage == 3.0
