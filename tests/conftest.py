import boa
import pytest
from eth_account import Account as EthAccount
from eth_utils import keccak

POOL_ROLE: bytes = keccak(b"POOL_ROLE")
LIQUIDATOR_ROLE: bytes = keccak(b"LIQUIDATOR_ROLE")

PRICER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


@pytest.fixture(scope="session")
def deployer():
    acc = boa.env.generate_address("deployer")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(scope="session")
def pricer_account():
    return EthAccount.from_key(PRICER_KEY)


@pytest.fixture(scope="session")
def pricer(pricer_account):
    addr = pricer_account.address
    boa.env.set_balance(addr, 10 * 10**18)
    return addr


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
def liquidator_account():
    acc = boa.env.generate_address("liquidator")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


@pytest.fixture(autouse=True)
def isolate():
    with boa.env.anchor():
        yield


@pytest.fixture(scope="session")
def condition_id():
    return b"\xab" * 32


@pytest.fixture(scope="session")
def token_id():
    return 1


@pytest.fixture()
def mock_usdc(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC20.vy")


@pytest.fixture()
def mock_ctf(deployer):
    with boa.env.prank(deployer):
        return boa.load("tests/mocks/MockERC1155.vy")


@pytest.fixture()
def address_provider(deployer):
    with boa.env.prank(deployer):
        return boa.load("contracts/registry/AddressProvider.vy")


@pytest.fixture()
def market_registry(deployer):
    with boa.env.prank(deployer):
        return boa.load("contracts/market/MarketRegistry.vy")


@pytest.fixture()
def interest_rate_model(deployer):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/lending/InterestRateModel.vy",
            50,
            8000,
            400,
            7500,
        )


@pytest.fixture()
def price_feed(deployer, pricer, condition_id):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/oracle/pricefeed/PriceFeed.vy",
            condition_id,
            pricer,
            200,
            3600,
            3000,
            600,
        )


@pytest.fixture()
def premium_oracle(deployer, pricer, condition_id):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/oracle/premium/PremiumOracle.vy",
            condition_id,
            pricer,
        )


@pytest.fixture()
def collateral_manager(deployer, condition_id, mock_ctf, price_feed, market_registry):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/collateral/CollateralManager.vy",
            condition_id,
            mock_ctf.address,
            price_feed.address,
            market_registry.address,
        )


@pytest.fixture()
def lending_pool(
    deployer,
    condition_id,
    mock_usdc,
    collateral_manager,
    premium_oracle,
    interest_rate_model,
    market_registry,
    price_feed,
):
    with boa.env.prank(deployer):
        pool = boa.load(
            "contracts/lending/LendingPool.vy",
            condition_id,
            mock_usdc.address,
            collateral_manager.address,
            premium_oracle.address,
            interest_rate_model.address,
            market_registry.address,
            price_feed.address,
            86400,
            604800,
        )
        collateral_manager.grantRole(POOL_ROLE, pool.address)
        premium_oracle.set_authorized_pool(pool.address)
    return pool


@pytest.fixture()
def liquidator_contract(
    deployer,
    condition_id,
    lending_pool,
    collateral_manager,
    price_feed,
    mock_usdc,
    mock_ctf,
    liquidator_account,
):
    with boa.env.prank(deployer):
        liq = boa.load(
            "contracts/liquidation/Liquidator.vy",
            condition_id,
            lending_pool.address,
            collateral_manager.address,
            price_feed.address,
            mock_usdc.address,
            mock_ctf.address,
            500,
        )
        collateral_manager.grantRole(LIQUIDATOR_ROLE, liq.address)
        lending_pool.grantRole(LIQUIDATOR_ROLE, liq.address)
    return liq


@pytest.fixture()
def setup_market(deployer, market_registry, condition_id):
    resolution_time = 2_000_000_000
    with boa.env.prank(deployer):
        market_registry.onboard_market(
            condition_id,
            resolution_time,
            7000,
            500_000 * 10**6,
            100_000 * 10**6,
        )
    return resolution_time


@pytest.fixture()
def funded_lender(mock_usdc, lender, lending_pool, deployer):
    amount = 1_000_000 * 10**6
    with boa.env.prank(deployer):
        mock_usdc.mint(lender, amount)
    with boa.env.prank(lender):
        mock_usdc.approve(lending_pool.address, amount)
    return amount


@pytest.fixture()
def funded_borrower(mock_ctf, borrower, collateral_manager, token_id, deployer):
    amount = 1000 * 10**18
    with boa.env.prank(deployer):
        mock_ctf.mint(borrower, token_id, amount)
    with boa.env.prank(borrower):
        mock_ctf.setApprovalForAll(collateral_manager.address, True)
    return amount


@pytest.fixture()
def price_feed_blueprint(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(
            "contracts/oracle/pricefeed/PriceFeed.vy"
        ).deploy_as_blueprint()


@pytest.fixture()
def price_feed_factory(deployer, price_feed_blueprint):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/oracle/pricefeed/factory/PriceFeedFactory.vy",
            price_feed_blueprint.address,
        )


@pytest.fixture()
def premium_oracle_blueprint(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(
            "contracts/oracle/premium/PremiumOracle.vy"
        ).deploy_as_blueprint()


@pytest.fixture()
def premium_oracle_factory(deployer, premium_oracle_blueprint):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/oracle/premium/factory/PremiumOracleFactory.vy",
            premium_oracle_blueprint.address,
        )


@pytest.fixture()
def collateral_manager_blueprint(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(
            "contracts/collateral/CollateralManager.vy"
        ).deploy_as_blueprint()


@pytest.fixture()
def collateral_manager_factory(deployer, collateral_manager_blueprint):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/collateral/factory/CollateralManagerFactory.vy",
            collateral_manager_blueprint.address,
        )


@pytest.fixture()
def lending_pool_blueprint(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(
            "contracts/lending/LendingPool.vy"
        ).deploy_as_blueprint()


@pytest.fixture()
def lending_pool_factory(deployer, lending_pool_blueprint):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/lending/factory/LendingPoolFactory.vy",
            lending_pool_blueprint.address,
        )


@pytest.fixture()
def liquidator_blueprint(deployer):
    with boa.env.prank(deployer):
        return boa.load_partial(
            "contracts/liquidation/Liquidator.vy"
        ).deploy_as_blueprint()


@pytest.fixture()
def liquidator_factory(deployer, liquidator_blueprint):
    with boa.env.prank(deployer):
        return boa.load(
            "contracts/liquidation/factory/LiquidatorFactory.vy",
            liquidator_blueprint.address,
        )
