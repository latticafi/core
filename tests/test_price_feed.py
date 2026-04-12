"""
PriceFeed tests: signed price submissions, deviation filter, circuit breaker.
"""

import boa
import pytest
from eth_account import Account

from conftest import ORACLE_SIGNER_ADDRESS, sign_price

CONDITION_ID = b"\xca\xfe" + b"\x00" * 30


@pytest.fixture
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def feed(admin):
    return boa.load(
        "contracts/PriceFeed.vy",
        ORACLE_SIGNER_ADDRESS,
        admin,
        10**14,
        2 * 10**17,
        3600,
    )


def _submit(feed, condition_id, price, ts_offset=0):
    ts = boa.env.evm.patch.timestamp + ts_offset
    deadline = ts + 3600
    sig = sign_price(feed.address, condition_id, price, ts, deadline, 1)
    feed.submit_price(condition_id, price, ts, deadline, sig)


class TestPriceSubmit:
    def test_first_submit(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        price, ts = feed.get_price(CONDITION_ID)
        assert price == 5 * 10**17
        assert ts > 0

    def test_sequential_submits(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        _submit(feed, CONDITION_ID, 51 * 10**16)
        price, _ = feed.get_price(CONDITION_ID)
        assert price == 51 * 10**16

    def test_wrong_signer_reverts(self, feed):
        bad_key = "0x" + "bb" * 31 + "bb"
        ts = boa.env.evm.patch.timestamp
        deadline = ts + 3600
        domain_data = {
            "name": "LatticaPriceFeed",
            "version": "1",
            "chainId": 1,
            "verifyingContract": feed.address,
        }
        message_types = {
            "PriceAttestation": [
                {"name": "conditionId", "type": "bytes32"},
                {"name": "price", "type": "uint256"},
                {"name": "timestamp", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        }
        message_data = {
            "conditionId": CONDITION_ID,
            "price": 5 * 10**17,
            "timestamp": ts,
            "deadline": deadline,
        }
        signed = Account.sign_typed_data(
            bad_key,
            domain_data=domain_data,
            message_types=message_types,
            message_data=message_data,
        )
        with boa.reverts("wrong signer"):
            feed.submit_price(CONDITION_ID, 5 * 10**17, ts, deadline, signed.signature)

    def test_expired_attestation_reverts(self, feed):
        ts = boa.env.evm.patch.timestamp
        deadline = ts - 1
        sig = sign_price(feed.address, CONDITION_ID, 5 * 10**17, ts, deadline, 1)
        with boa.reverts("attestation expired"):
            feed.submit_price(CONDITION_ID, 5 * 10**17, ts, deadline, sig)

    def test_price_above_one_reverts(self, feed):
        with boa.reverts("invalid price"):
            _submit(feed, CONDITION_ID, 2 * 10**18)

    def test_anyone_can_submit(self, feed):
        """Permissionless — no auth check on caller."""
        rando = boa.env.generate_address("rando")
        ts = boa.env.evm.patch.timestamp
        deadline = ts + 3600
        sig = sign_price(feed.address, CONDITION_ID, 5 * 10**17, ts, deadline, 1)
        with boa.env.prank(rando):
            feed.submit_price(CONDITION_ID, 5 * 10**17, ts, deadline, sig)
        price, _ = feed.get_price(CONDITION_ID)
        assert price == 5 * 10**17


class TestDeviationFilter:
    def test_below_min_deviation_reverts(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        with boa.reverts("below min deviation"):
            _submit(feed, CONDITION_ID, 5 * 10**17 + 1)


class TestCircuitBreaker:
    def test_large_move_trips_breaker(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        _submit(feed, CONDITION_ID, 75 * 10**16)

        assert feed.is_circuit_broken(CONDITION_ID)
        price, _ = feed.get_price(CONDITION_ID)
        assert price == 5 * 10**17

    def test_breaker_blocks_submits(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        _submit(feed, CONDITION_ID, 75 * 10**16)
        boa.env.time_travel(seconds=1)
        with boa.reverts("circuit breaker active"):
            _submit(feed, CONDITION_ID, 52 * 10**16)

    def test_breaker_expires_after_cooldown(self, feed):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        _submit(feed, CONDITION_ID, 75 * 10**16)

        boa.env.time_travel(seconds=3601)

        assert not feed.is_circuit_broken(CONDITION_ID)
        _submit(feed, CONDITION_ID, 52 * 10**16)

    def test_admin_resets_breaker(self, feed, admin):
        _submit(feed, CONDITION_ID, 5 * 10**17)
        boa.env.time_travel(seconds=1)
        _submit(feed, CONDITION_ID, 75 * 10**16)
        assert feed.is_circuit_broken(CONDITION_ID)
        with boa.env.prank(admin):
            feed.reset_circuit_breaker(CONDITION_ID)
        assert not feed.is_circuit_broken(CONDITION_ID)
