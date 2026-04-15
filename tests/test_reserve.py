"""
Reserve tests: deposit notifications, loss coverage, dynamic retention rate.
"""

import boa
import pytest


@pytest.fixture
def owner():
    return boa.env.generate_address("owner")


@pytest.fixture
def pool():
    return boa.env.generate_address("pool")


@pytest.fixture
def usdc():
    return boa.load("tests/mocks/MockUSDC.vy")


@pytest.fixture
def reserve(usdc, pool, owner):
    return boa.load(
        "contracts/Reserve.vy",
        usdc.address,
        pool,
        owner,
        10_000 * 10**6,  # target: 10k USDC
        1000,  # base retention: 10%
        5000,  # max retention: 50%
    )


class TestRetentionRate:
    def test_empty_reserve_returns_max_retention(self, reserve):
        assert reserve.current_retention_bps() == 5000

    def test_funded_reserve_returns_base_retention(self, reserve, usdc):
        # Fund reserve to target
        usdc.mint(reserve.address, 10_000 * 10**6)
        assert reserve.current_retention_bps() == 1000

    def test_half_funded_returns_midpoint(self, reserve, usdc):
        # Fund to 50% of target
        usdc.mint(reserve.address, 5_000 * 10**6)
        rate = reserve.current_retention_bps()
        # Should be midpoint between 1000 and 5000 = 3000
        assert rate == 3000

    def test_overfunded_returns_base(self, reserve, usdc):
        usdc.mint(reserve.address, 20_000 * 10**6)
        assert reserve.current_retention_bps() == 1000


class TestDeposit:
    def test_deposit_from_pool(self, reserve, pool):
        with boa.env.prank(pool):
            reserve.deposit(1_000 * 10**6)

    def test_deposit_from_non_pool_reverts(self, reserve):
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not pool"):
                reserve.deposit(1_000 * 10**6)


class TestCoverLoss:
    def test_covers_up_to_balance(self, reserve, usdc, pool):
        usdc.mint(reserve.address, 5_000 * 10**6)
        with boa.env.prank(pool):
            covered = reserve.cover_loss(3_000 * 10**6)
        assert covered == 3_000 * 10**6
        assert usdc.balanceOf(reserve.address) == 2_000 * 10**6

    def test_partial_cover_when_underfunded(self, reserve, usdc, pool):
        usdc.mint(reserve.address, 2_000 * 10**6)
        with boa.env.prank(pool):
            covered = reserve.cover_loss(5_000 * 10**6)
        assert covered == 2_000 * 10**6
        assert usdc.balanceOf(reserve.address) == 0

    def test_zero_balance_covers_nothing(self, reserve, pool):
        with boa.env.prank(pool):
            covered = reserve.cover_loss(1_000 * 10**6)
        assert covered == 0


class TestHealthy:
    def test_unhealthy_when_empty(self, reserve):
        assert not reserve.is_healthy()

    def test_healthy_when_at_target(self, reserve, usdc):
        usdc.mint(reserve.address, 10_000 * 10**6)
        assert reserve.is_healthy()


class TestOwner:
    def test_set_retention_bps_validates(self, reserve, owner):
        with boa.env.prank(owner):
            with boa.reverts("max must be >= base"):
                reserve.set_retention_bps(5000, 1000)
