import boa
import pytest
from eth_utils import keccak

POOL_ROLE: bytes = keccak(b"POOL_ROLE")
LIQUIDATOR_ROLE: bytes = keccak(b"LIQUIDATOR_ROLE")


def test_initial_state(collateral_manager, condition_id, mock_ctf, price_feed, market_registry):
    assert collateral_manager.condition_id() == condition_id
    assert collateral_manager.ctf() == mock_ctf.address
    assert collateral_manager.price_feed() == price_feed.address
    assert collateral_manager.market_registry() == market_registry.address


def test_deposit_collateral(
    collateral_manager, lending_pool, mock_ctf, borrower, token_id, funded_borrower
):
    deposit_amount = 100 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)

    assert mock_ctf.balanceOf(collateral_manager.address, token_id) == deposit_amount
    pos = collateral_manager.positions(borrower)
    assert pos[0] == deposit_amount
    assert pos[1] == token_id
    assert pos[2] == 0
    assert pos[3] == 0
    assert collateral_manager.total_collateral() == deposit_amount


def test_deposit_collateral_no_role_reverts(collateral_manager, borrower, token_id):
    with boa.reverts():
        with boa.env.prank(borrower):
            collateral_manager.deposit_collateral(borrower, 100 * 10**18, token_id)


def test_deposit_collateral_zero_amount_reverts(
    collateral_manager, lending_pool, borrower, token_id
):
    with boa.reverts("zero amount"):
        with boa.env.prank(lending_pool.address):
            collateral_manager.deposit_collateral(borrower, 0, token_id)


def test_deposit_collateral_duplicate_reverts(
    collateral_manager, lending_pool, mock_ctf, borrower, token_id, funded_borrower
):
    deposit_amount = 100 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)

    with boa.reverts("position exists"):
        with boa.env.prank(lending_pool.address):
            collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)


def test_release_collateral(
    collateral_manager, lending_pool, mock_ctf, borrower, token_id, funded_borrower
):
    deposit_amount = 100 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)

    with boa.env.prank(lending_pool.address):
        collateral_manager.release_collateral(borrower)

    assert mock_ctf.balanceOf(borrower, token_id) == funded_borrower
    assert mock_ctf.balanceOf(collateral_manager.address, token_id) == 0
    pos = collateral_manager.positions(borrower)
    assert pos[0] == 0
    assert collateral_manager.total_collateral() == 0


def test_seize_collateral(
    collateral_manager,
    lending_pool,
    mock_ctf,
    borrower,
    token_id,
    funded_borrower,
    deployer,
    liquidator_contract,
):
    deposit_amount = 100 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)

    with boa.env.prank(liquidator_contract.address):
        collateral_manager.seize_collateral(borrower)

    assert mock_ctf.balanceOf(liquidator_contract.address, token_id) == deposit_amount
    assert mock_ctf.balanceOf(collateral_manager.address, token_id) == 0
    pos = collateral_manager.positions(borrower)
    assert pos[0] == 0
    assert collateral_manager.total_collateral() == 0


def test_set_debt(
    collateral_manager, lending_pool, mock_ctf, borrower, token_id, funded_borrower
):
    deposit_amount = 100 * 10**18
    debt_amount = 50 * 10**6
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)
        collateral_manager.set_debt(borrower, debt_amount)

    pos = collateral_manager.positions(borrower)
    assert pos[3] == debt_amount


def test_get_health_factor_no_position(collateral_manager, borrower):
    assert collateral_manager.get_health_factor(borrower) == 2**256 - 1


def test_get_health_factor(
    collateral_manager,
    lending_pool,
    mock_ctf,
    borrower,
    token_id,
    funded_borrower,
    pricer,
    price_feed,
    setup_market,
):
    deposit_amount = 100
    debt = 70
    price = 10**18

    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, deposit_amount, token_id)
        collateral_manager.set_debt(borrower, debt)

    with boa.env.prank(pricer):
        price_feed.push_price(price)

    # collateral_value = (100 * 1e18) // 1e18 = 100
    # adjusted = (100 * 7000) // 10000 = 70
    # health = (70 * 10000) // 70 = 10000
    health = collateral_manager.get_health_factor(borrower)
    assert health == 10000


def test_onERC1155Received(collateral_manager, deployer):
    result = collateral_manager.onERC1155Received(
        deployer, deployer, 0, 0, b""
    )
    assert result == bytes.fromhex("f23a6e61")
