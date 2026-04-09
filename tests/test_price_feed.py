"""
PriceFeed tests: price updates, deviation filter, circuit breaker.
"""

import boa
import pytest

CONDITION_ID = b"\xca\xfe" + b"\x00" * 30


@pytest.fixture
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def updater():
    return boa.env.generate_address("updater")


@pytest.fixture
def feed(updater, admin):
    return boa.load(
        "contracts/PriceFeed.vy",
        updater,
        admin,
        10**14,  # min deviation (0.01%)
        2 * 10**17,  # circuit breaker threshold (20%)
        3600,  # cooldown (1 hour)
    )


class TestPriceUpdate:
    def test_first_update(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
        price, ts = feed.get_price(CONDITION_ID)
        assert price == 5 * 10**17
        assert ts > 0

    def test_sequential_updates(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            feed.update_price(CONDITION_ID, 51 * 10**16)
        price, _ = feed.get_price(CONDITION_ID)
        assert price == 51 * 10**16

    def test_non_updater_reverts(self, feed):
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not updater"):
                feed.update_price(CONDITION_ID, 5 * 10**17)

    def test_price_above_one_reverts(self, feed, updater):
        with boa.env.prank(updater):
            with boa.reverts("invalid price"):
                feed.update_price(CONDITION_ID, 2 * 10**18)


class TestDeviationFilter:
    def test_below_min_deviation_reverts(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            with boa.reverts("below min deviation"):
                feed.update_price(CONDITION_ID, 5 * 10**17 + 1)  # tiny change


class TestCircuitBreaker:
    def test_large_move_trips_breaker(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            # 25% move (above 20% threshold)
            feed.update_price(CONDITION_ID, 75 * 10**16)

        assert feed.is_circuit_broken(CONDITION_ID)
        # Price should NOT be stored (old price remains)
        price, _ = feed.get_price(CONDITION_ID)
        assert price == 5 * 10**17

    def test_breaker_blocks_updates(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            feed.update_price(CONDITION_ID, 75 * 10**16)  # trips breaker
            with boa.reverts("circuit breaker active"):
                feed.update_price(CONDITION_ID, 52 * 10**16)

    def test_breaker_expires_after_cooldown(self, feed, updater):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            feed.update_price(CONDITION_ID, 75 * 10**16)  # trips breaker

        boa.env.time_travel(seconds=3601)

        assert not feed.is_circuit_broken(CONDITION_ID)
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 52 * 10**16)  # works now

    def test_admin_resets_breaker(self, feed, updater, admin):
        with boa.env.prank(updater):
            feed.update_price(CONDITION_ID, 5 * 10**17)
            feed.update_price(CONDITION_ID, 75 * 10**16)
        assert feed.is_circuit_broken(CONDITION_ID)
        with boa.env.prank(admin):
            feed.reset_circuit_breaker(CONDITION_ID)
        assert not feed.is_circuit_broken(CONDITION_ID)
