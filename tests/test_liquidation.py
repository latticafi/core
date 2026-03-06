import boa
import pytest
from eth_account import Account as EthAccount
from eth_utils import keccak
from eth_utils import keccak as keccak256

POOL_ROLE: bytes = keccak(b"POOL_ROLE")
LIQUIDATOR_ROLE: bytes = keccak(b"LIQUIDATOR_ROLE")

PRICER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def sign_premium_quote(
    pricer_key, oracle_address, borrower, condition_id,
    premium_bps, amount, deadline, nonce, chain_id=1,
):
    domain_data = {
        "name": "LatticaPremiumOracle",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": oracle_address,
    }
    message_types = {
        "PremiumQuote": [
            {"name": "borrower", "type": "address"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "premiumBps", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
        ],
    }
    message_data = {
        "borrower": borrower,
        "conditionId": "0x" + condition_id.hex() if isinstance(condition_id, bytes) else condition_id,
        "premiumBps": premium_bps,
        "amount": amount,
        "deadline": deadline,
        "nonce": nonce,
    }
    signed = EthAccount.sign_typed_data(
        pricer_key,
        domain_data=domain_data,
        message_types=message_types,
        message_data=message_data,
    )
    return signed.signature


def _do_borrow_setup_and_borrow(
    lending_pool, collateral_manager, mock_ctf, price_feed,
    premium_oracle, deployer, pricer, lender, borrower, token_id,
    funded_lender, funded_borrower,
    deposit_amount=100_000 * 10**6,
    collateral_amount=500 * 10**18,
    borrow_amount=10_000 * 10**6,
):
    with boa.env.prank(pricer):
        price_feed.push_price(7 * 10**17)

    with boa.env.prank(lender):
        lending_pool.deposit(deposit_amount)

    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, collateral_amount, token_id)

    premium_bps = 200
    deadline = 2_000_000_000
    nonce = premium_oracle.get_nonce(borrower)
    sig = sign_premium_quote(
        PRICER_KEY, premium_oracle.address, borrower,
        premium_oracle.condition_id(), premium_bps, borrow_amount, deadline, nonce,
    )
    with boa.env.prank(borrower):
        lending_pool.borrow(borrow_amount, borrower, 604800, premium_bps, deadline, sig)


def test_initial_state(
    liquidator_contract,
    condition_id,
    lending_pool,
    collateral_manager,
    price_feed,
    mock_usdc,
    mock_ctf,
):
    assert liquidator_contract.condition_id() == condition_id
    assert liquidator_contract.lending_pool() == lending_pool.address
    assert liquidator_contract.collateral_manager() == collateral_manager.address
    assert liquidator_contract.price_feed() == price_feed.address
    assert liquidator_contract.usdc_e() == mock_usdc.address
    assert liquidator_contract.ctf() == mock_ctf.address
    assert liquidator_contract.liquidation_fee_bps() == 500


def test_is_liquidatable_no_loan(liquidator_contract, borrower):
    assert liquidator_contract.is_liquidatable(borrower) is False


def test_is_liquidatable_expired_epoch(
    liquidator_contract,
    lending_pool,
    collateral_manager,
    mock_usdc,
    mock_ctf,
    price_feed,
    premium_oracle,
    deployer,
    pricer,
    lender,
    borrower,
    token_id,
    setup_market,
    funded_lender,
    funded_borrower,
):
    _do_borrow_setup_and_borrow(
        lending_pool, collateral_manager, mock_ctf, price_feed,
        premium_oracle, deployer, pricer, lender, borrower, token_id,
        funded_lender, funded_borrower,
    )

    boa.env.time_travel(seconds=604800 + 1)

    assert liquidator_contract.is_liquidatable(borrower) is True


def test_is_liquidatable_health_below_threshold(
    liquidator_contract,
    lending_pool,
    collateral_manager,
    mock_usdc,
    mock_ctf,
    price_feed,
    premium_oracle,
    market_registry,
    deployer,
    pricer,
    lender,
    borrower,
    token_id,
    condition_id,
    setup_market,
    funded_lender,
    funded_borrower,
):
    _do_borrow_setup_and_borrow(
        lending_pool, collateral_manager, mock_ctf, price_feed,
        premium_oracle, deployer, pricer, lender, borrower, token_id,
        funded_lender, funded_borrower,
    )

    debt_value = 5 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.set_debt(borrower, debt_value)

    boa.env.time_travel(seconds=60)
    with boa.env.prank(pricer):
        price_feed.push_price(1 * 10**16)

    health = collateral_manager.get_health_factor(borrower)
    assert health < 10000
    assert liquidator_contract.is_liquidatable(borrower) is True


def test_liquidate(
    liquidator_contract,
    lending_pool,
    collateral_manager,
    mock_usdc,
    mock_ctf,
    price_feed,
    premium_oracle,
    deployer,
    pricer,
    lender,
    borrower,
    liquidator_account,
    token_id,
    setup_market,
    funded_lender,
    funded_borrower,
):
    _do_borrow_setup_and_borrow(
        lending_pool, collateral_manager, mock_ctf, price_feed,
        premium_oracle, deployer, pricer, lender, borrower, token_id,
        funded_lender, funded_borrower,
    )

    boa.env.time_travel(seconds=604800 + 1)
    assert liquidator_contract.is_liquidatable(borrower) is True

    price = 7 * 10**17
    collateral_amount = 500 * 10**18
    borrow_amount = 10_000 * 10**6
    collateral_value = (collateral_amount * price) // 10**18
    fee = (collateral_value * 500) // 10_000
    to_pool = collateral_value - fee
    if to_pool > borrow_amount:
        to_pool = borrow_amount

    with boa.env.prank(deployer):
        mock_usdc.mint(liquidator_account, to_pool)
    with boa.env.prank(liquidator_account):
        mock_usdc.approve(liquidator_contract.address, to_pool)

    with boa.env.prank(liquidator_account):
        liquidator_contract.liquidate(borrower)

    loan = lending_pool.loans(borrower)
    assert loan[5] is False

    assert mock_ctf.balanceOf(liquidator_account, token_id) == collateral_amount
    assert mock_ctf.balanceOf(collateral_manager.address, token_id) == 0


def test_set_liquidation_fee(liquidator_contract, deployer):
    with boa.env.prank(deployer):
        liquidator_contract.set_liquidation_fee(1000)
    assert liquidator_contract.liquidation_fee_bps() == 1000


def test_set_liquidation_fee_non_admin_reverts(liquidator_contract, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            liquidator_contract.set_liquidation_fee(1000)
