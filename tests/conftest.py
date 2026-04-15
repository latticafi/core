"""
Shared fixtures for Lattica protocol tests.
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
DEFAULT_PRICE = 6 * 10**17  # 0.60

# Pricer key (quote-engine signer)

PRICER_KEY = "0x" + "de" * 31 + "ad"
PRICER_ACCOUNT = Account.from_key(PRICER_KEY)
PRICER_ADDRESS = PRICER_ACCOUNT.address

# Oracle signer key (price signer)

ORACLE_KEY = "0x" + "ab" * 31 + "cd"
ORACLE_ACCOUNT = Account.from_key(ORACLE_KEY)
ORACLE_SIGNER_ADDRESS = ORACLE_ACCOUNT.address


def sign_quote(
    oracle_address,
    borrower,
    condition_id,
    premium_bps,
    amount,
    collateral_amount,
    epoch_length,
    deadline,
    nonce,
    chain_id,
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
            {"name": "collateralAmount", "type": "uint256"},
            {"name": "epochLength", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
        ],
    }
    message_data = {
        "borrower": borrower,
        "conditionId": condition_id,
        "premiumBps": premium_bps,
        "amount": amount,
        "collateralAmount": collateral_amount,
        "epochLength": epoch_length,
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


def sign_price(pool_address, condition_id, price, timestamp, deadline, chain_id):
    """Sign a PriceAttestation. Domain is LendingPool (it verifies inline)."""
    domain_data = {
        "name": "LatticaPriceFeed",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": pool_address,
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


def make_price_params(pool_address, condition_id, price=None):
    """Build (price, timestamp, deadline, signature) for inline price."""
    if price is None:
        price = DEFAULT_PRICE
    ts = boa.env.evm.patch.timestamp
    deadline = ts + 3600
    sig = sign_price(pool_address, condition_id, price, ts, deadline, 1)
    return price, ts, deadline, sig


# Accounts


@pytest.fixture
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def operator():
    return boa.env.generate_address("operator")


@pytest.fixture
def lender():
    return boa.env.generate_address("lender")


@pytest.fixture
def borrower_addr():
    return boa.env.generate_address("borrower")


# Mocks


@pytest.fixture
def usdc():
    return boa.load("tests/mocks/MockUSDC.vy")


@pytest.fixture
def ctf_token():
    return boa.load("tests/mocks/MockCTFToken.vy")


# Deploy full stack


@pytest.fixture
def deploy_stack(usdc, ctf_token, admin, operator):
    pool = boa.load("contracts/LendingPool.vy", usdc.address, ctf_token.address, admin)
    core = boa.load("contracts/PoolCore.vy", usdc.address, pool.address, admin)
    oracle = boa.load("contracts/PremiumOracle.vy", PRICER_ADDRESS, core.address, admin)
    controller = boa.load(
        "contracts/PortfolioController.vy", core.address, admin, 10_000_000 * 10**6
    )

    with boa.env.prank(admin):
        core.set_peripherals(oracle.address, controller.address)

    reserve = boa.load(
        "contracts/Reserve.vy", usdc.address, pool.address, admin, 10_000 * 10**6, 1000, 5000
    )

    with boa.env.prank(admin):
        pool.initialize(core.address, reserve.address, ORACLE_SIGNER_ADDRESS, operator)

    return {
        "pool": pool,
        "core": core,
        "oracle": oracle,
        "controller": controller,
        "reserve": reserve,
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
        core.set_market(CONDITION_ID, (TOKEN_ID, 1000, 9000, resolution, 2 * 3600, True))
