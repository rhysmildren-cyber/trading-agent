from agent import risk


def _gate(**kw):
    defaults = dict(
        signal="buy",
        equity=100_000,
        prev_equity=100_000,
        starting_capital=100_000,
        kill_switch_already_tripped=False,
        halted=False,
    )
    defaults.update(kw)
    return risk.gate(**defaults)


def test_normal_trade_approved():
    assert _gate().approved


def test_kill_switch_trips_at_25_percent_drawdown():
    r = _gate(equity=74_999, prev_equity=76_000)
    assert not r.approved and r.trip_kill_switch
    # just above the line (prev_equity close so the daily halt doesn't fire too)
    assert _gate(equity=75_001, prev_equity=76_000).approved


def test_kill_switch_stays_tripped():
    r = _gate(kill_switch_already_tripped=True, equity=200_000)
    assert not r.approved and "manual review" in r.block_reason


def test_daily_halt_at_10_percent_day_loss():
    r = _gate(equity=89_000, prev_equity=100_000)
    assert not r.approved and r.trip_daily_halt
    assert _gate(equity=90_001, prev_equity=100_000).approved


def test_halted_blocks_trading():
    r = _gate(halted=True)
    assert not r.approved and "daily_halt" in r.block_reason


def test_kill_switch_takes_priority_over_halt():
    r = _gate(equity=70_000, halted=True)
    assert r.trip_kill_switch
