"""
PremiumOracle tests: EIP-712 quote verification, nonce management, pricer rotation.
"""

import boa
import pytest
from eth_account import Account

from conftest import sign_quote

CONDITION_ID = b"\xca\xfe" + b"\x00" * 30
PRICER_KEY = "0x" + "de" * 31 + "ad"
PRICER_ACCOUNT = Account.from_key(PRICER_KEY)
PRICER_ADDRESS = PRICER_ACCOUNT.address

AMOUNT = 500 * 10**6
COLLATERAL = 1000 * 10**6
EPOCH = 24 * 3600


@pytest.fixture
def owner():
    return boa.env.generate_address("owner")


@pytest.fixture
def pool():
    return boa.env.generate_address("pool")


@pytest.fixture
def oracle(pool, owner):
    return boa.load("contracts/PremiumOracle.vy", PRICER_ADDRESS, pool, owner)


@pytest.fixture
def borrower():
    return boa.env.generate_address("borrower")


class TestVerifyQuote:
    def test_valid_quote(self, oracle, pool, borrower):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )
        with boa.env.prank(pool):
            result = oracle.verify_quote(
                borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
            )
        assert result

    def test_increments_nonce(self, oracle, pool, borrower):
        assert oracle.get_nonce(borrower) == 0
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )
        with boa.env.prank(pool):
            oracle.verify_quote(
                borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
            )
        assert oracle.get_nonce(borrower) == 1

    def test_expired_quote_reverts(self, oracle, pool, borrower):
        deadline = boa.env.evm.patch.timestamp - 1
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )
        with boa.env.prank(pool):
            with boa.reverts("quote expired"):
                oracle.verify_quote(
                    borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
                )

    def test_wrong_nonce_reverts(self, oracle, pool, borrower):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 1, 1
        )
        with boa.env.prank(pool):
            with boa.reverts("invalid nonce"):
                oracle.verify_quote(
                    borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 1, sig
                )

    def test_non_pool_caller_reverts(self, oracle, borrower):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )
        with boa.env.prank(borrower):
            with boa.reverts("not pool"):
                oracle.verify_quote(
                    borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
                )

    def test_paused_reverts(self, oracle, pool, borrower, owner):
        with boa.env.prank(owner):
            oracle.set_paused(True)
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )
        with boa.env.prank(pool):
            with boa.reverts("paused"):
                oracle.verify_quote(
                    borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
                )


class TestPricerRotation:
    def test_rotate_pricer(self, oracle, owner):
        new_pricer = boa.env.generate_address("new_pricer")
        with boa.env.prank(owner):
            oracle.set_pricer(new_pricer)
        assert oracle.pricer() == new_pricer

    def test_old_signature_fails_after_rotation(self, oracle, pool, borrower, owner):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address, borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, 1
        )

        new_pricer = boa.env.generate_address("new_pricer")
        with boa.env.prank(owner):
            oracle.set_pricer(new_pricer)

        with boa.env.prank(pool):
            with boa.reverts("wrong signer"):
                oracle.verify_quote(
                    borrower, CONDITION_ID, 300, AMOUNT, COLLATERAL, EPOCH, deadline, 0, sig
                )

    def test_zero_address_pricer_reverts(self, oracle, owner):
        with boa.env.prank(owner):
            with boa.reverts("zero address"):
                oracle.set_pricer("0x" + "00" * 20)
