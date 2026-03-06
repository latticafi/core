import boa
import pytest


RESOLUTION_TIME = 2_000_000_000
COLLATERAL_FACTOR = 7000
MAX_EXPOSURE = 500_000 * 10**6
MIN_LIQUIDITY = 100_000 * 10**6
CUTOFF_BUFFER = 14400


def _onboard(registry, deployer, cid, resolution_time=RESOLUTION_TIME):
    with boa.env.prank(deployer):
        registry.onboard_market(
            cid, resolution_time, COLLATERAL_FACTOR, MAX_EXPOSURE, MIN_LIQUIDITY
        )


def test_onboard_market(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    assert market_registry.is_registered(condition_id) is True
    params = market_registry.get_market_params(condition_id)
    assert params[0] == COLLATERAL_FACTOR
    assert params[1] == MAX_EXPOSURE
    assert params[2] == MIN_LIQUIDITY
    assert params[3] == RESOLUTION_TIME
    assert params[4] == RESOLUTION_TIME - CUTOFF_BUFFER
    assert params[5] is True
    assert params[6] is False
    assert market_registry.get_cutoff(condition_id) == RESOLUTION_TIME - CUTOFF_BUFFER
    assert market_registry.market_count() == 1


def test_onboard_market_non_owner_reverts(market_registry, lender, condition_id):
    with boa.env.prank(lender):
        with boa.reverts():
            market_registry.onboard_market(
                condition_id, RESOLUTION_TIME, COLLATERAL_FACTOR, MAX_EXPOSURE, MIN_LIQUIDITY
            )


def test_onboard_duplicate_reverts(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    with boa.env.prank(deployer):
        with boa.reverts("market already registered"):
            market_registry.onboard_market(
                condition_id, RESOLUTION_TIME, COLLATERAL_FACTOR, MAX_EXPOSURE, MIN_LIQUIDITY
            )


def test_onboard_bad_collateral_factor_reverts(market_registry, deployer):
    cid = b"\xcd" * 32
    with boa.env.prank(deployer):
        with boa.reverts("collateral factor exceeds max"):
            market_registry.onboard_market(
                cid, RESOLUTION_TIME, 10001, MAX_EXPOSURE, MIN_LIQUIDITY
            )


def test_onboard_resolution_too_soon_reverts(market_registry, deployer):
    cid = b"\xef" * 32
    too_soon = boa.env.evm.patch.timestamp + CUTOFF_BUFFER
    with boa.env.prank(deployer):
        with boa.reverts("resolution too soon"):
            market_registry.onboard_market(
                cid, too_soon, COLLATERAL_FACTOR, MAX_EXPOSURE, MIN_LIQUIDITY
            )


def test_pause_market(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    with boa.env.prank(deployer):
        market_registry.pause_market(condition_id)
    params = market_registry.get_market_params(condition_id)
    assert params[6] is True


def test_unpause_market(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    with boa.env.prank(deployer):
        market_registry.pause_market(condition_id)
        market_registry.unpause_market(condition_id)
    params = market_registry.get_market_params(condition_id)
    assert params[6] is False


def test_deboard_market(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    with boa.env.prank(deployer):
        market_registry.deboard_market(condition_id)
    params = market_registry.get_market_params(condition_id)
    assert params[5] is False


def test_update_collateral_factor(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    with boa.env.prank(deployer):
        market_registry.update_collateral_factor(condition_id, 8000)
    params = market_registry.get_market_params(condition_id)
    assert params[0] == 8000


def test_update_max_exposure_cap(market_registry, deployer, condition_id):
    _onboard(market_registry, deployer, condition_id)
    new_cap = 1_000_000 * 10**6
    with boa.env.prank(deployer):
        market_registry.update_max_exposure_cap(condition_id, new_cap)
    params = market_registry.get_market_params(condition_id)
    assert params[1] == new_cap
