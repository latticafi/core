import boa
import pytest
from eth_abi import encode as abi_encode
from eth_utils import keccak as keccak256

LIQUIDATOR_ROLE: bytes = keccak256(b"LIQUIDATOR_ROLE")
MAX_BPS = 10000


def setup_premium(premium_oracle, pricer, epoch, premium_bps=200):
    salt = b"\x01" * 32
    commitment = keccak256(abi_encode(["uint256", "bytes32"], [premium_bps, salt]))
    with boa.env.prank(pricer):
        premium_oracle.commit(epoch, commitment)
    boa.env.time_travel(seconds=15)
    with boa.env.prank(pricer):
        premium_oracle.reveal(epoch, premium_bps, salt)


def do_deposit(lending_pool, lender, amount):
    with boa.env.prank(lender):
        lending_pool.deposit(amount)


def do_borrow(lending_pool, deployer, borrower, amount):
    with boa.env.prank(deployer):
        lending_pool.borrow(amount, borrower)


# --- Deposit / Withdraw ---


def test_deposit(lending_pool, mock_usdc, lender, deployer, funded_lender):
    deposit_amount = 100_000 * 10**6
    pool_balance_before = mock_usdc.balanceOf(lending_pool.address)
    do_deposit(lending_pool, lender, deposit_amount)

    assert lending_pool.total_deposits() == deposit_amount
    assert lending_pool.shares(lender) > 0
    assert lending_pool.total_shares() > 0
    assert mock_usdc.balanceOf(lending_pool.address) == pool_balance_before + deposit_amount


def test_deposit_zero_reverts(lending_pool, lender):
    with boa.reverts("zero amount"):
        with boa.env.prank(lender):
            lending_pool.deposit(0)


def test_withdraw(lending_pool, mock_usdc, lender, deployer, funded_lender):
    deposit_amount = 100_000 * 10**6
    do_deposit(lending_pool, lender, deposit_amount)

    lender_shares = lending_pool.shares(lender)
    lender_balance_before = mock_usdc.balanceOf(lender)

    with boa.env.prank(lender):
        lending_pool.withdraw(lender_shares)

    assert lending_pool.total_deposits() == 0
    assert lending_pool.shares(lender) == 0
    assert mock_usdc.balanceOf(lender) == lender_balance_before + deposit_amount


def test_withdraw_insufficient_shares_reverts(lending_pool, lender):
    with boa.reverts("insufficient shares"):
        with boa.env.prank(lender):
            lending_pool.withdraw(1)


# --- Share value ---


def test_get_share_value(lending_pool, mock_usdc, lender, deployer, funded_lender):
    deposit_amount = 100_000 * 10**6
    do_deposit(lending_pool, lender, deposit_amount)

    lender_shares = lending_pool.shares(lender)
    value = lending_pool.get_share_value(lender_shares)
    assert value == deposit_amount


# --- Borrow ---


def test_borrow(
    lending_pool,
    mock_usdc,
    lender,
    borrower,
    deployer,
    pricer,
    premium_oracle,
    interest_rate_model,
    funded_lender,
    setup_market,
):
    deposit_amount = 100_000 * 10**6
    borrow_amount = 10_000 * 10**6
    premium_bps = 200

    do_deposit(lending_pool, lender, deposit_amount)
    setup_premium(premium_oracle, pricer, 1, premium_bps)

    borrower_balance_before = mock_usdc.balanceOf(borrower)

    utilization = (borrow_amount * MAX_BPS) // deposit_amount
    rate_bps = interest_rate_model.get_rate(utilization)
    interest = (borrow_amount * rate_bps) // MAX_BPS
    premium = (borrow_amount * premium_bps) // MAX_BPS
    net = borrow_amount - interest - premium

    do_borrow(lending_pool, deployer, borrower, borrow_amount)

    assert lending_pool.total_borrowed() == borrow_amount
    assert mock_usdc.balanceOf(borrower) == borrower_balance_before + net

    loan = lending_pool.loans(borrower)
    assert loan[0] == borrow_amount  # principal
    assert loan[1] == interest  # interest_paid
    assert loan[2] == premium  # premium_paid
    assert loan[3] == rate_bps  # rate_bps
    assert loan[4] == 1  # epoch
    assert loan[6] is True  # is_active


def test_borrow_no_liquidity_reverts(
    lending_pool,
    mock_usdc,
    deployer,
    borrower,
    pricer,
    premium_oracle,
    setup_market,
):
    setup_premium(premium_oracle, pricer, 1)

    with boa.reverts("insufficient liquidity"):
        do_borrow(lending_pool, deployer, borrower, 10_000 * 10**6)


def test_borrow_when_paused_reverts(lending_pool, deployer, borrower, setup_market):
    with boa.env.prank(deployer):
        lending_pool.pause()

    with boa.reverts("not open"):
        do_borrow(lending_pool, deployer, borrower, 10_000 * 10**6)


# --- Repay ---


def test_repay(
    lending_pool,
    mock_usdc,
    lender,
    borrower,
    deployer,
    pricer,
    premium_oracle,
    collateral_manager,
    mock_ctf,
    token_id,
    funded_lender,
    funded_borrower,
    setup_market,
):
    deposit_amount = 100_000 * 10**6
    borrow_amount = 10_000 * 10**6

    do_deposit(lending_pool, lender, deposit_amount)
    setup_premium(premium_oracle, pricer, 1)

    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, 100 * 10**18, token_id)

    do_borrow(lending_pool, deployer, borrower, borrow_amount)

    loan = lending_pool.loans(borrower)
    principal = loan[0]

    with boa.env.prank(deployer):
        mock_usdc.mint(borrower, principal)
    with boa.env.prank(borrower):
        mock_usdc.approve(lending_pool.address, principal)
        lending_pool.repay(borrower)

    loan_after = lending_pool.loans(borrower)
    assert loan_after[6] is False  # is_active
    assert lending_pool.total_borrowed() == 0


# --- Epoch management ---


def test_advance_epoch(lending_pool, deployer, setup_market):
    assert lending_pool.current_epoch() == 1

    with boa.env.prank(deployer):
        lending_pool.advance_epoch()

    assert lending_pool.current_epoch() == 2
    assert lending_pool.epoch_state() == 1  # EpochState.OPEN is flag bit 0 = value 1


def test_advance_epoch_non_admin_reverts(lending_pool, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            lending_pool.advance_epoch()


def test_pause_unpause(lending_pool, deployer):
    with boa.env.prank(deployer):
        lending_pool.pause()
    assert lending_pool.epoch_state() == 2  # PAUSED flag

    with boa.env.prank(deployer):
        lending_pool.unpause()
    assert lending_pool.epoch_state() == 1  # OPEN flag


# --- Handle liquidation proceeds ---


def test_handle_liquidation_proceeds(
    lending_pool,
    mock_usdc,
    deployer,
    lender,
    borrower,
    pricer,
    premium_oracle,
    funded_lender,
    setup_market,
    liquidator_contract,
):
    deposit_amount = 100_000 * 10**6
    borrow_amount = 10_000 * 10**6

    do_deposit(lending_pool, lender, deposit_amount)
    setup_premium(premium_oracle, pricer, 1)
    do_borrow(lending_pool, deployer, borrower, borrow_amount)

    loan = lending_pool.loans(borrower)
    principal = loan[0]
    premium_paid = loan[2]

    premium_reserve_before = lending_pool.premium_reserve()
    assert premium_reserve_before == premium_paid

    recovered = principal - 500 * 10**6
    shortfall = principal - recovered

    with boa.env.prank(deployer):
        mock_usdc.mint(liquidator_contract.address, recovered)
    with boa.env.prank(liquidator_contract.address):
        mock_usdc.approve(lending_pool.address, recovered)
        lending_pool.handle_liquidation_proceeds(borrower, recovered)

    loan_after = lending_pool.loans(borrower)
    assert loan_after[6] is False  # is_active
    assert lending_pool.total_borrowed() == 0

    if premium_reserve_before >= shortfall:
        assert lending_pool.premium_reserve() == premium_reserve_before - shortfall
    else:
        assert lending_pool.premium_reserve() == 0
