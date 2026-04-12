"""
Liquidator tests: collateral seizure, operator settlement, emergency claims.
"""

import boa
import pytest

CONDITION_ID = b"\xca\xfe" + b"\x00" * 30
TOKEN_ID = 42


@pytest.fixture
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def pool():
    return boa.env.generate_address("pool")


@pytest.fixture
def liquidator_operator():
    return boa.env.generate_address("liquidator")


@pytest.fixture
def ctf_token():
    return boa.load("tests/mocks/MockCTFToken.vy")


@pytest.fixture
def liquidator(pool, liquidator_operator, ctf_token, admin):
    return boa.load("contracts/Liquidator.vy", pool, liquidator_operator, ctf_token.address, admin)


class TestSeize:
    def test_seize_records_pending(self, liquidator, pool):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        assert liquidator.pending_count() == 1
        assert liquidator.total_seized_principal() == 500 * 10**6

    def test_multiple_seize(self, liquidator, pool):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
            liquidator.seize(2, TOKEN_ID, 2000 * 10**6, CONDITION_ID, 800 * 10**6, 2_000_000_000)
        assert liquidator.pending_count() == 2
        assert liquidator.total_seized_principal() == 1300 * 10**6

    def test_non_pool_reverts(self, liquidator):
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not pool"):
                liquidator.seize(1, TOKEN_ID, 1000, CONDITION_ID, 500, 2_000_000_000)


class TestSettle:
    def test_settle_clears_pending(self, liquidator, pool, liquidator_operator):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        with boa.env.prank(liquidator_operator):
            liquidator.settle(1, 300 * 10**6)
        assert liquidator.pending_count() == 0
        assert liquidator.total_recovered() == 300 * 10**6

    def test_settle_zero_recovery(self, liquidator, pool, liquidator_operator):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        with boa.env.prank(liquidator_operator):
            liquidator.settle(1, 0)
        assert liquidator.pending_count() == 0
        assert liquidator.total_recovered() == 0

    def test_double_settle_reverts(self, liquidator, pool, liquidator_operator):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        with boa.env.prank(liquidator_operator):
            liquidator.settle(1, 300 * 10**6)
            with boa.reverts("already settled"):
                liquidator.settle(1, 100 * 10**6)

    def test_settle_nonexistent_reverts(self, liquidator, liquidator_operator):
        with boa.env.prank(liquidator_operator):
            with boa.reverts("no pending liquidation"):
                liquidator.settle(999, 100 * 10**6)

    def test_non_bot_reverts(self, liquidator, pool):
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not operator"):
                liquidator.settle(1, 300 * 10**6)


class TestEmergencyClaim:
    def test_admin_claims_stuck_collateral(self, liquidator, pool, ctf_token, admin):
        # Give liquidator some collateral
        ctf_token.mint(liquidator.address, TOKEN_ID, 1000 * 10**6)
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)

        with boa.env.prank(admin):
            liquidator.emergency_claim(1)

        assert liquidator.pending_count() == 0
        assert ctf_token.balanceOf(admin, TOKEN_ID) == 1000 * 10**6

    def test_non_admin_reverts(self, liquidator, pool, ctf_token):
        ctf_token.mint(liquidator.address, TOKEN_ID, 1000 * 10**6)
        with boa.env.prank(pool):
            liquidator.seize(1, TOKEN_ID, 1000 * 10**6, CONDITION_ID, 500 * 10**6, 2_000_000_000)
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("ownable: caller is not the owner"):
                liquidator.emergency_claim(1)


class TestBotRotation:
    def test_set_bot(self, liquidator, admin):
        new_operator = boa.env.generate_address("new_operator")
        with boa.env.prank(admin):
            liquidator.set_operator(new_operator)
        assert liquidator.operator() == new_operator

    def test_set_bot_zero_reverts(self, liquidator, admin):
        with boa.env.prank(admin):
            with boa.reverts("zero address"):
                liquidator.set_operator("0x" + "00" * 20)
