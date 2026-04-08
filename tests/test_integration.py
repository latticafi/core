import boa
from eth_account import Account as EthAccount
from eth_utils.crypto import keccak as keccak256

POOL_ROLE: bytes = keccak256(b"POOL_ROLE")
LIQUIDATOR_ROLE: bytes = keccak256(b"LIQUIDATOR_ROLE")

PRICER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def sign_premium_quote(
    pricer_key,
    oracle_address,
    borrower,
    condition_id,
    premium_bps,
    amount,
    deadline,
    nonce,
    chain_id=1,
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
        "conditionId": "0x" + condition_id.hex()
        if isinstance(condition_id, bytes)
        else condition_id,
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


def test_full_lending_cycle(
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
    with boa.env.prank(pricer):
        price_feed.push_price(7 * 10**17)

    lender_deposit = 100_000 * 10**6
    with boa.env.prank(lender):
        lending_pool.deposit(lender_deposit)

    assert lending_pool.total_deposits() == lender_deposit
    assert lending_pool.total_shares() == lender_deposit
    assert lending_pool.shares(lender) == lender_deposit

    collateral_amount = 500 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, collateral_amount, token_id)

    borrow_amount = 10_000 * 10**6
    premium_bps = 200
    deadline = 2_000_000_000
    borrower_usdc_before = mock_usdc.balanceOf(borrower)

    nonce = premium_oracle.get_nonce(borrower)
    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        borrower,
        premium_oracle.condition_id(),
        premium_bps,
        borrow_amount,
        deadline,
        nonce,
    )
    with boa.env.prank(borrower):
        lending_pool.borrow(borrow_amount, borrower, 604800, premium_bps, deadline, sig)

    loan = lending_pool.loans(borrower)
    principal = loan[0]
    interest_paid = loan[1]
    premium_paid = loan[2]
    assert principal == borrow_amount
    assert loan[5] is True

    net = borrow_amount - interest_paid - premium_paid
    assert mock_usdc.balanceOf(borrower) == borrower_usdc_before + net

    assert lending_pool.total_deposits() == lender_deposit + interest_paid
    assert lending_pool.total_borrowed() == borrow_amount
    assert lending_pool.premium_reserve() == premium_paid

    with boa.env.prank(deployer):
        mock_usdc.mint(borrower, borrow_amount)
    with boa.env.prank(borrower):
        mock_usdc.approve(lending_pool.address, borrow_amount)
        lending_pool.repay(borrower)

    loan_after = lending_pool.loans(borrower)
    assert loan_after[5] is False
    assert lending_pool.total_borrowed() == 0
    assert mock_ctf.balanceOf(borrower, token_id) == funded_borrower


def test_liquidation_cycle(
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
    with boa.env.prank(pricer):
        price_feed.push_price(7 * 10**17)

    lender_deposit = 100_000 * 10**6
    with boa.env.prank(lender):
        lending_pool.deposit(lender_deposit)

    collateral_amount = 500 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, collateral_amount, token_id)

    borrow_amount = 10_000 * 10**6
    premium_bps = 200
    deadline = 2_000_000_000

    nonce = premium_oracle.get_nonce(borrower)
    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        borrower,
        premium_oracle.condition_id(),
        premium_bps,
        borrow_amount,
        deadline,
        nonce,
    )
    with boa.env.prank(borrower):
        lending_pool.borrow(borrow_amount, borrower, 604800, premium_bps, deadline, sig)

    boa.env.time_travel(seconds=604800 + 1)
    assert liquidator_contract.is_liquidatable(borrower) is True

    price = 7 * 10**17
    collateral_value = (collateral_amount * price) // 10**18
    fee = (collateral_value * 500) // 10_000
    to_pool = collateral_value - fee
    if to_pool > borrow_amount:
        to_pool = borrow_amount

    with boa.env.prank(deployer):
        mock_usdc.mint(liquidator_account, to_pool)
    with boa.env.prank(liquidator_account):
        mock_usdc.approve(liquidator_contract.address, to_pool)

    pool_usdc_before = mock_usdc.balanceOf(lending_pool.address)

    with boa.env.prank(liquidator_account):
        liquidator_contract.liquidate(borrower)

    loan = lending_pool.loans(borrower)
    assert loan[5] is False
    assert lending_pool.total_borrowed() == 0

    assert mock_ctf.balanceOf(liquidator_account, token_id) == collateral_amount
    assert mock_ctf.balanceOf(collateral_manager.address, token_id) == 0

    assert mock_usdc.balanceOf(lending_pool.address) == pool_usdc_before + to_pool


def test_share_value_increases_with_interest(
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
    with boa.env.prank(pricer):
        price_feed.push_price(7 * 10**17)

    lender_deposit = 100_000 * 10**6
    with boa.env.prank(lender):
        lending_pool.deposit(lender_deposit)

    share_value_before = lending_pool.get_share_value(10**6)

    collateral_amount = 500 * 10**18
    with boa.env.prank(lending_pool.address):
        collateral_manager.deposit_collateral(borrower, collateral_amount, token_id)

    borrow_amount = 10_000 * 10**6
    premium_bps = 200
    deadline = 2_000_000_000

    nonce = premium_oracle.get_nonce(borrower)
    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        borrower,
        premium_oracle.condition_id(),
        premium_bps,
        borrow_amount,
        deadline,
        nonce,
    )
    with boa.env.prank(borrower):
        lending_pool.borrow(borrow_amount, borrower, 604800, premium_bps, deadline, sig)

    share_value_after = lending_pool.get_share_value(10**6)

    assert share_value_after > share_value_before
