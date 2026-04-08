import boa


def test_initial_state(price_feed, condition_id, pricer):
    assert price_feed.condition_id() == condition_id
    assert price_feed.authorized_updater() == pricer
    assert price_feed.price() == 0
    assert price_feed.deviation_threshold_bps() == 200


def test_push_first_price(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)
    assert price_feed.price() == 5 * 10**17
    assert price_feed.last_update() > 0
    assert price_feed.prev_price() == 0


def test_push_price_unauthorized_reverts(price_feed, lender):
    with boa.env.prank(lender):
        with boa.reverts("unauthorized"):
            price_feed.push_price(5 * 10**17)


def test_push_price_out_of_range_reverts(price_feed, pricer):
    with boa.env.prank(pricer):
        with boa.reverts("price out of range"):
            price_feed.push_price(10**18 + 1)


def test_push_price_deviation_check(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)

    small_bump = 5 * 10**17 + 5 * 10**15
    with boa.env.prank(pricer):
        with boa.reverts("deviation too small"):
            price_feed.push_price(small_bump)

    with boa.env.prank(pricer):
        price_feed.push_price(6 * 10**17)
    assert price_feed.price() == 6 * 10**17


def test_get_price_staleness(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)

    _price, is_stale = price_feed.get_price()
    assert _price == 5 * 10**17
    assert is_stale is False

    boa.env.time_travel(seconds=3601)

    _price, is_stale = price_feed.get_price()
    assert is_stale is True


def test_circuit_breaker_trips(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)
        price_feed.push_price(2 * 10**17)

    assert price_feed.is_circuit_breaker_active() is True


def test_circuit_breaker_blocks_push(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)
        price_feed.push_price(2 * 10**17)

    assert price_feed.is_circuit_breaker_active() is True

    with boa.env.prank(pricer):
        with boa.reverts("circuit breaker active"):
            price_feed.push_price(3 * 10**17)

    boa.env.time_travel(seconds=601)

    with boa.env.prank(pricer):
        price_feed.push_price(3 * 10**17)
    assert price_feed.price() == 3 * 10**17


def test_circuit_breaker_auto_resets(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(5 * 10**17)
        price_feed.push_price(2 * 10**17)

    assert price_feed.is_circuit_breaker_active() is True

    boa.env.time_travel(seconds=601)

    with boa.env.prank(pricer):
        price_feed.push_price(22 * 10**16)

    assert price_feed.is_circuit_breaker_active() is False
    assert price_feed.circuit_breaker_tripped() is False


def test_get_price_returns_tuple(price_feed, pricer):
    with boa.env.prank(pricer):
        price_feed.push_price(7 * 10**17)

    result = price_feed.get_price()
    assert isinstance(result, tuple)
    assert result[0] == 7 * 10**17
    assert result[1] is False
