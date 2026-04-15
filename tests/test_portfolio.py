"""
PortfolioController tests: capacity checks, concentration limits, circuit breaker.
"""

import boa
import pytest

CONDITION_A = b"\xaa" + b"\x00" * 31
CONDITION_B = b"\xbb" + b"\x00" * 31
EPOCH_END = 2_000_000_000


@pytest.fixture
def owner():
    return boa.env.generate_address("owner")


@pytest.fixture
def pool():
    return boa.env.generate_address("pool")


@pytest.fixture
def ctrl(pool, owner):
    return boa.load(
        "contracts/PortfolioController.vy",
        pool,
        owner,
        1_000_000 * 10**6,  # 1M max total exposure
    )


class TestCapacity:
    def test_within_capacity(self, ctrl):
        assert ctrl.check_capacity(CONDITION_A, 500_000 * 10**6, EPOCH_END)

    def test_exceeds_total_cap(self, ctrl):
        assert not ctrl.check_capacity(CONDITION_A, 2_000_000 * 10**6, EPOCH_END)

    def test_per_condition_cap(self, ctrl, owner):
        with boa.env.prank(owner):
            ctrl.set_condition_cap(CONDITION_A, 100_000 * 10**6)
        assert not ctrl.check_capacity(CONDITION_A, 200_000 * 10**6, EPOCH_END)
        assert ctrl.check_capacity(CONDITION_A, 50_000 * 10**6, EPOCH_END)


class TestOrigination:
    def test_record_updates_exposure(self, ctrl, pool):
        with boa.env.prank(pool):
            ctrl.record_origination(CONDITION_A, 100_000 * 10**6, EPOCH_END)
        assert ctrl.total_exposure() == 100_000 * 10**6
        assert ctrl.condition_exposure(CONDITION_A) == 100_000 * 10**6

    def test_multiple_conditions(self, ctrl, pool):
        with boa.env.prank(pool):
            ctrl.record_origination(CONDITION_A, 100_000 * 10**6, EPOCH_END)
            ctrl.record_origination(CONDITION_B, 200_000 * 10**6, EPOCH_END)
        assert ctrl.total_exposure() == 300_000 * 10**6
        assert ctrl.condition_exposure(CONDITION_A) == 100_000 * 10**6
        assert ctrl.condition_exposure(CONDITION_B) == 200_000 * 10**6

    def test_origination_from_non_pool_reverts(self, ctrl):
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not pool"):
                ctrl.record_origination(CONDITION_A, 100_000 * 10**6, EPOCH_END)


class TestSettlement:
    def test_settlement_decreases_exposure(self, ctrl, pool):
        with boa.env.prank(pool):
            ctrl.record_origination(CONDITION_A, 100_000 * 10**6, EPOCH_END)
            ctrl.record_settlement(CONDITION_A, 100_000 * 10**6, 0, EPOCH_END)
        assert ctrl.total_exposure() == 0
        assert ctrl.condition_exposure(CONDITION_A) == 0


class TestCluster:
    def test_cluster_budget(self, ctrl, owner, pool):
        with boa.env.prank(owner):
            ctrl.set_cluster_assignment(CONDITION_A, 1)
            ctrl.set_cluster_assignment(CONDITION_B, 1)
            ctrl.set_cluster_budget(1, 150_000 * 10**6)

        with boa.env.prank(pool):
            ctrl.record_origination(CONDITION_A, 100_000 * 10**6, EPOCH_END)

        # Second origination would exceed cluster budget
        assert not ctrl.check_capacity(CONDITION_B, 100_000 * 10**6, EPOCH_END)
        assert ctrl.check_capacity(CONDITION_B, 40_000 * 10**6, EPOCH_END)


class TestCircuitBreaker:
    def test_circuit_breaker_blocks_capacity(self, ctrl, owner):
        with boa.env.prank(owner):
            ctrl.set_circuit_breaker(True)
        assert not ctrl.check_capacity(CONDITION_A, 1, EPOCH_END)

    def test_circuit_breaker_blocks_origination(self, ctrl, owner, pool):
        with boa.env.prank(owner):
            ctrl.set_circuit_breaker(True)
        with boa.env.prank(pool):
            with boa.reverts("circuit breaker active"):
                ctrl.record_origination(CONDITION_A, 100, EPOCH_END)
