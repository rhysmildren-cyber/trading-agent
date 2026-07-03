import pytest

from agent import costs, ledger
from agent.config import COST_RATE, DEPLOY_FRACTION, STARTING_CAPITAL


def test_buy_pays_costs():
    qty, paid = costs.buy_with_cash(10_000, price=100.0)
    assert paid == pytest.approx(10_000 * COST_RATE)  # 0.35% -> $35
    assert qty == pytest.approx((10_000 - paid) / 100.0)


def test_sell_pays_costs():
    cash, paid = costs.sell_qty(10.0, price=100.0)
    assert paid == pytest.approx(1000 * COST_RATE)
    assert cash == pytest.approx(1000 - paid)


def test_buy_deploys_95_percent():
    p = ledger.Portfolio(cash=STARTING_CAPITAL)
    p2, fill = ledger.buy(p, price=50_000.0)
    assert p2.cash == pytest.approx(STARTING_CAPITAL * (1 - DEPLOY_FRACTION))
    assert fill["fee_paid"] == pytest.approx(STARTING_CAPITAL * DEPLOY_FRACTION * COST_RATE)
    assert p2.position == "long"


def test_round_trip_loses_both_sides_of_costs():
    p = ledger.Portfolio(cash=STARTING_CAPITAL)
    p, _ = ledger.buy(p, price=50_000.0)
    p, _ = ledger.sell_all(p, price=50_000.0)  # flat price: only costs bite
    assert p.position == "flat"
    loss = STARTING_CAPITAL - p.cash
    expected = STARTING_CAPITAL * DEPLOY_FRACTION * COST_RATE  # entry
    expected += (STARTING_CAPITAL * DEPLOY_FRACTION - expected) * COST_RATE  # exit (approx)
    assert loss == pytest.approx(expected, rel=1e-6)


def test_mark_tracks_peak_and_drawdown():
    p = ledger.Portfolio(cash=0, qty=1.0)
    p, eq, dd = ledger.mark(p, price=100.0)
    assert (eq, dd) == (100.0, 0.0)
    p, eq, dd = ledger.mark(p, price=80.0)
    assert eq == 80.0 and dd == pytest.approx(0.20)
    assert p.peak_equity == 100.0
