# pragma version ~=0.4.0

"""
@title Lattica Views
@author Lattica Protocol
@license MIT
@notice Read-only pool-level snapshots. Price-dependent views
        are served by the backend directly.
"""

from interfaces import IPoolCore as IPoolCore
from interfaces import ILendingPool as ILendingPool
from interfaces import IReserve as IReserve
from interfaces import IPortfolioController as IPortfolioController


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


pool: public(address)
core: public(address)
controller: public(address)
reserve: public(address)


@deploy
def __init__(
    _pool: address, _core: address, _controller: address, _reserve: address
):
    self.pool = _pool
    self.core = _core
    self.controller = _controller
    self.reserve = _reserve


@external
@view
def get_pool_snapshot() -> PoolSnapshot:
    c: IPoolCore = IPoolCore(self.core)
    r: IReserve = IReserve(self.reserve)
    ctrl: IPortfolioController = IPortfolioController(self.controller)

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
    )


@external
@view
def get_lender_balance(lender: address) -> (uint256, uint256):
    c: IPoolCore = IPoolCore(self.core)
    shares: uint256 = staticcall c.share_balance(lender)
    price: uint256 = staticcall c.share_price()
    value: uint256 = (shares * price) // 10**6
    return (shares, value)


@external
@view
def preview_liquidation_price(
    collateral_amount: uint256, borrow_amount: uint256
) -> uint256:
    return staticcall IPoolCore(self.core).preview_liquidation_price(
        collateral_amount, borrow_amount
    )
