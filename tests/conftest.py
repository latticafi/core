import boa
import pytest

# accounts


@pytest.fixture(scope="session")
def deployer():
    acc = boa.env.generate_address("deployer")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(scope="session")
def pricer():
    """Authorized backend wallet that commits/reveals WARBIRD premiums
    and pushes PriceFeed updates."""
    acc = boa.env.generate_address("pricer")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(scope="session")
def lender():
    acc = boa.env.generate_address("lender")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(scope="session")
def borrower():
    acc = boa.env.generate_address("borrower")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(scope="session")
def liquidator():
    acc = boa.env.generate_address("liquidator")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


# EVM isolation


@pytest.fixture(autouse=True)
def isolate():
    with boa.env.anchor():
        yield


# TODO:
# mock tokens & contracts
#
# - mock USDC.e (ERC20, 6 decimals)
# - mock ConditionalTokens (ERC1155 CTF)
#     - prepareCondition()
#     - splitPosition() → mint YES/NO tokens
#     - mergePositions() → burn YES+NO → USDC.e
# - mock CTF Exchange (orderbook — accepts sells, returns USDC.e)
# - mock PriceFeed with set_price(conditionId, price) helper
# - mock PremiumOracle with set_premium(conditionId, epoch, bps) helper
#
# time travel helpers
#
# - advance_time(seconds) → fast-forward block timestamp
# - advance_to_cutoff(conditionId) → jump to resolution cutoff
# - advance_epoch() → jump to next epoch boundary
#
# market helpers
#
# - onboard_market(conditionId, resolution_time, collateral_factor,
#     max_exposure_cap, min_liquidity_depth) → admin registers
#     market in EpochManager, making it available for lending
# - create_market(conditionId, resolution_time) → sets up CTF
#   condition + mints YES/NO tokens for borrower + registers
#   cutoff in EpochManager
#
# wallet context
#
# In production, all user addresses are Safe wallets (Gnosis Safe).
# In tests, we use plain EOAs which is equivalent because:
# - The Builder Relayer submits standard txs FROM the Safe
# - Contracts see msg.sender = Safe address
# - We test with EOAs that behave identically at the contract level
# - Safe-specific behavior (deployment, approval batching) is
#   off-chain frontend logic, not contract logic
#
# For integration tests that need to simulate existing Polymarket
# positions (Path A: "Connect Wallet"), the borrower fixture is
# pre-funded with CTF tokens via splitPosition() in the market
# helper — this simulates a user who already holds positions.
