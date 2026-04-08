# pragma version ~=0.4.0

"""
@title Lattica Views
@author Lattica Protocol
@license MIT
@notice Read-only integrator views. Aggregates data from PoolCore
        and peripherals into single-call snapshots.
        Upgradeable — Factory stores this contract's address.
"""

from interfaces import IPoolCore as IPoolCore
from interfaces import ILendingPool as ILendingPool
from interfaces import IPriceFeed as IPriceFeed
from interfaces import IReserve as IReserve
from interfaces import IPortfolioController as IPortfolioController
from interfaces import IPremiumOracle as IPremiumOracle
from interfaces import ILiquidator as ILiquidator


# Data Structures

struct PoolSnapshot:
    total_assets: uint256
    total_borrowed: uint256
    available_liquidity: uint256
    utilization: uint256
    share_price: uint256
    current_rate: uint256
    maintenance_margin: uint256
    reserve_balance: uint256
    reserve_healthy: bool
    controller_circuit_broken: bool
    paused: bool
    total_loans: uint256
    pending_liquidations: uint256


struct LoanSnapshot:
    health_factor: uint256
    liquidation_price: uint256
    current_ltv: uint256


# Storage

pool: public(address)
core: public(address)
price_feed: public(address)
controller: public(address)
reserve: public(address)
oracle: public(address)
liquidator: public(address)

# Constructor

@deploy
def __init__(
    _pool: address,
    _core: address,
    _price_feed: address,
    _controller: address,
    _reserve: address,
    _oracle: address,
    _liquidator: address,
):
    self.pool = _pool
    self.core = _core
    self.price_feed = _price_feed
    self.controller = _controller
    self.reserve = _reserve
    self.oracle = _oracle
    self.liquidator = _liquidator


# Pool snapshot

@external
@view
def get_pool_snapshot() -> PoolSnapshot:
    c: IPoolCore = IPoolCore(self.core)
    r: IReserve = IReserve(self.reserve)
    ctrl: IPortfolioController = IPortfolioController(self.controller)
    liq: ILiquidator = ILiquidator(self.liquidator)

    return PoolSnapshot(
        total_assets=staticcall c.total_assets(),
        total_borrowed=staticcall c.total_borrowed(),
        available_liquidity=staticcall c.available_liquidity(),
        utilization=staticcall c.utilization(),
        share_price=staticcall c.share_price(),
        current_rate=staticcall c.current_rate(),
        maintenance_margin=staticcall c.maintenance_margin_bps(),
        reserve_balance=staticcall r.reserve_balance(),
        reserve_healthy=staticcall r.is_healthy(),
        controller_circuit_broken=staticcall ctrl.is_circuit_broken(),
        paused=staticcall ILendingPool(self.pool).paused(),
        total_loans=staticcall c.next_loan_id(),
        pending_liquidations=staticcall liq.pending_count(),
    )


# Loan views

@external
@view
def get_loan_snapshot(loan_id: uint256) -> LoanSnapshot:
    c: IPoolCore = IPoolCore(self.core)
    return LoanSnapshot(
        health_factor=staticcall c.health_factor(loan_id),
        liquidation_price=staticcall c.get_liquidation_price(loan_id),
        current_ltv=staticcall c.current_ltv(loan_id),
    )


# Borrower pre-trade views

@external
@view
def preview_borrow(
    condition_id: bytes32,
    collateral_amount: uint256,
    borrow_amount: uint256,
) -> (uint256, uint256, uint256):
    """

    @return (liquidation_price, current_rate, current_price)
    """
    c: IPoolCore = IPoolCore(self.core)
    pf: IPriceFeed = IPriceFeed(self.price_feed)

    liq_price: uint256 = staticcall c.preview_liquidation_price(
        collateral_amount, borrow_amount
    )
    rate: uint256 = staticcall c.current_rate()
    price: uint256 = 0
    ts: uint256 = 0
    price, ts = staticcall pf.get_price(condition_id)
    return (liq_price, rate, price)


@external
@view
def get_borrower_nonce(borrower: address) -> uint256:
    return staticcall IPremiumOracle(self.oracle).get_nonce(borrower)


# Market views

@external
@view
def get_market_price(condition_id: bytes32) -> (uint256, uint256, bool):
    """
    @return (price, updated_at, is_circuit_broken)
    """
    pf: IPriceFeed = IPriceFeed(self.price_feed)
    price: uint256 = 0
    ts: uint256 = 0
    price, ts = staticcall pf.get_price(condition_id)
    broken: bool = staticcall pf.is_circuit_broken(condition_id)
    return (price, ts, broken)


@external
@view
def get_market_exposure(condition_id: bytes32) -> uint256:
    return staticcall IPortfolioController(self.controller).condition_exposure(
        condition_id
    )


@external
@view
def get_lender_balance(lender: address) -> (uint256, uint256):
    """
    @return (shares, usdc_value)
    """
    c: IPoolCore = IPoolCore(self.core)
    shares: uint256 = staticcall c.share_balance(lender)
    price: uint256 = staticcall c.share_price()
    value: uint256 = (shares * price) // 10**6
    return (shares, value)
