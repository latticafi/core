"""
Integration tests against a Polygon fork.
"""

import json
import os

import boa
import pytest

from conftest import ORACLE_SIGNER_ADDRESS, PRICER_ADDRESS

pytestmark = pytest.mark.skipif(
    not os.environ.get("RPC_URL"),
    reason="RPC_URL not set",
)

USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

ERC20_ABI = json.dumps(
    [
        {
            "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
            "name": "transfer",
            "outputs": [{"type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
            "name": "approve",
            "outputs": [{"type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]
)

USDC_WHALE = "0x625E7708f30cA75bfd92586e17077590C60eb4cD"


@pytest.fixture(scope="module", autouse=True)
def fork():
    boa.env.fork(os.environ["RPC_URL"])
    yield


@pytest.fixture(scope="module")
def usdc():
    return boa.loads_abi(ERC20_ABI).at(USDC_E)


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture(scope="module")
def lender(usdc):
    addr = boa.env.generate_address("lender")
    boa.env.set_balance(addr, 10**18)
    with boa.env.prank(USDC_WHALE):
        usdc.transfer(addr, 50_000 * 10**6)
    return addr


@pytest.fixture(scope="module")
def stack(admin):
    guardian = boa.env.generate_address("guardian")

    pool = boa.load("contracts/LendingPool.vy", USDC_E, CTF, admin)
    core = boa.load("contracts/PoolCore.vy", USDC_E, pool.address, admin)
    oracle = boa.load("contracts/PremiumOracle.vy", PRICER_ADDRESS, core.address, admin)
    controller = boa.load(
        "contracts/PortfolioController.vy", core.address, admin, 10_000_000 * 10**6
    )
    with boa.env.prank(admin):
        core.set_peripherals(oracle.address, controller.address)

    reserve = boa.load(
        "contracts/Reserve.vy", USDC_E, pool.address, admin, 100_000 * 10**6, 1000, 3000
    )

    with boa.env.prank(admin):
        pool.initialize(core.address, reserve.address, ORACLE_SIGNER_ADDRESS, guardian)

    return {"pool": pool, "core": core}


class TestForkDeploy:
    def test_stack_initialized(self, stack):
        assert stack["pool"].initialized()

    def test_usdc_wired(self, stack):
        assert stack["pool"].usdc() == USDC_E

    def test_ctf_wired(self, stack):
        assert stack["pool"].ctf_token() == CTF


class TestForkDeposit:
    def test_deposit_real_usdc(self, stack, usdc, lender):
        pool = stack["pool"]
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        assert shares > 0

    def test_withdraw_real_usdc(self, stack, usdc, lender):
        pool = stack["pool"]
        core = stack["core"]
        shares = core.share_balance(lender)
        bal_before = usdc.balanceOf(lender)
        with boa.env.prank(lender):
            pool.withdraw(shares)
        assert usdc.balanceOf(lender) > bal_before
        assert core.share_balance(lender) == 0
