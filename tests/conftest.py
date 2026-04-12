"""
Shared fixtures for Lattica protocol tests.
Uses titanoboa (boa) for Vyper testing.
"""

import boa
import pytest
from eth_account import Account

# Constants

CONDITION_ID = b"\xca\xfe" + b"\x00" * 30
TOKEN_ID = 42
INITIAL_DEPOSIT = 100_000 * 10**6
COLLATERAL_AMOUNT = 1_000 * 10**6
BORROW_AMOUNT = 400 * 10**6
EPOCH_24H = 24 * 3600
PREMIUM_BPS = 300

# Pricer key (quote-engine signer)

PRICER_KEY = "0x" + "de" * 31 + "ad"
PRICER_ACCOUNT = Account.from_key(PRICER_KEY)
PRICER_ADDRESS = PRICER_ACCOUNT.address

# Oracle signer key (price feed signer)

ORACLE_KEY = "0x" + "ab" * 31 + "cd"
ORACLE_ACCOUNT = Account.from_key(ORACLE_KEY)
ORACLE_SIGNER_ADDRESS = ORACLE_ACCOUNT.address


def sign_quote(
    oracle_address, borrower, condition_id, premium_bps, amount, deadline, nonce, chain_id
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
        "conditionId": condition_id,
        "premiumBps": premium_bps,
        "amount": amount,
        "deadline": deadline,
        "nonce": nonce,
    }
    signed = Account.sign_typed_data(
        PRICER_KEY,
        domain_data=domain_data,
        message_types=message_types,
        message_data=message_data,
    )
    return signed.signature


def sign_price(feed_address, condition_id, price, timestamp, deadline, chain_id):
    domain_data = {
        "name": "LatticaPriceFeed",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": feed_address,
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
        "conditionId": condition_id,
        "price": price,
        "timestamp": timestamp,
        "deadline": deadline,
    }
    signed = Account.sign_typed_data(
        ORACLE_KEY,
        domain_data=domain_data,
        message_types=message_types,
        message_data=message_data,
    )
    return signed.signature


def submit_signed_price(feed, condition_id, price):
    """Helper: sign and submit a price to the feed."""
    ts = boa.env.evm.patch.timestamp
    deadline = ts + 3600
    sig = sign_price(feed.address, condition_id, price, ts, deadline, 1)
    feed.submit_price(condition_id, price, ts, deadline, sig)


# Accounts


@pytest.fixture
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def guardian():
    return boa.env.generate_address("guardian")


@pytest.fixture
def lender():
    return boa.env.generate_address("lender")


@pytest.fixture
def borrower_addr():
    return boa.env.generate_address("borrower")


@pytest.fixture
def liquidator_operator():
    return boa.env.generate_address("liquidator")


# Mocks


@pytest.fixture
def usdc():
    return boa.load("tests/mocks/MockUSDC.vy")


@pytest.fixture
def ctf_token():
    return boa.load("tests/mocks/MockCTFToken.vy")


# Deploy full stack


@pytest.fixture
def price_feed(admin):
    feed = boa.load(
        "contracts/PriceFeed.vy",
        ORACLE_SIGNER_ADDRESS,
        admin,
        10**14,
        2 * 10**17,
        3600,
    )
    submit_signed_price(feed, CONDITION_ID, 6 * 10**17)
    return feed


@pytest.fixture
def deploy_stack(usdc, ctf_token, price_feed, admin, guardian, liquidator_operator):
    pool = boa.load("contracts/LendingPool.vy", usdc.address, ctf_token.address, admin)

    core = boa.load("contracts/PoolCore.vy", usdc.address, pool.address, price_feed.address, admin)

    oracle = boa.load("contracts/PremiumOracle.vy", PRICER_ADDRESS, core.address, admin)

    controller = boa.load(
        "contracts/PortfolioController.vy", core.address, admin, 10_000_000 * 10**6
    )

    with boa.env.prank(admin):
        core.set_peripherals(oracle.address, controller.address)

    reserve = boa.load(
        "contracts/Reserve.vy", usdc.address, pool.address, admin, 10_000 * 10**6, 1000, 5000
    )

    liquidator = boa.load(
        "contracts/Liquidator.vy", pool.address, liquidator_operator, ctf_token.address, admin
    )

    with boa.env.prank(admin):
        pool.initialize(
            core.address, liquidator.address, reserve.address, price_feed.address, guardian
        )

    return {
        "pool": pool,
        "core": core,
        "oracle": oracle,
        "controller": controller,
        "reserve": reserve,
        "liquidator": liquidator,
        "price_feed": price_feed,
    }


@pytest.fixture
def pool(deploy_stack):
    return deploy_stack["pool"]


@pytest.fixture
def core(deploy_stack):
    return deploy_stack["core"]


@pytest.fixture
def oracle(deploy_stack):
    return deploy_stack["oracle"]


@pytest.fixture
def controller(deploy_stack):
    return deploy_stack["controller"]


@pytest.fixture
def reserve(deploy_stack):
    return deploy_stack["reserve"]


@pytest.fixture
def liquidator(deploy_stack):
    return deploy_stack["liquidator"]


@pytest.fixture
def funded(pool, core, usdc, ctf_token, lender, borrower_addr, admin):
    usdc.mint(lender, INITIAL_DEPOSIT)
    with boa.env.prank(lender):
        usdc.approve(pool.address, 2**256 - 1)
        pool.deposit(INITIAL_DEPOSIT)

    usdc.mint(borrower_addr, 50_000 * 10**6)
    ctf_token.mint(borrower_addr, TOKEN_ID, COLLATERAL_AMOUNT)
    with boa.env.prank(borrower_addr):
        usdc.approve(pool.address, 2**256 - 1)
        ctf_token.setApprovalForAll(pool.address, True)

    resolution = boa.env.evm.patch.timestamp + 30 * 86400
    with boa.env.prank(admin):
        core.set_market(
            CONDITION_ID, (TOKEN_ID, 1000, 9000, 1_000_000 * 10**6, resolution, 2 * 3600, True)
        )
