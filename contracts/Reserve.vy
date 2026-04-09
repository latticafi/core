# pragma version ~=0.4.0

"""
@title Lattica Reserve
@notice Retained premium buffer that absorbs losses before lender capital.
        Dynamic retention rate: higher when reserve is depleted.
"""

from ethereum.ercs import IERC20
from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow

initializes: ownable
initializes: ow[ownable := ownable]

# Storage

usdc: public(IERC20)
pool: public(address)
reserve_target: public(uint256)
base_retention_bps: public(uint256)  # e.g. 1000 = 10%
max_retention_bps: public(uint256)  # e.g. 5000 = 50%

# Events

event ReserveDeposited:
    amount: uint256


event LossCovered:
    amount: uint256


# Constructor

@deploy
def __init__(
    usdc_addr: address,
    pool_addr: address,
    admin: address,
    _target: uint256,
    _base_retention: uint256,
    _max_retention: uint256,
):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(admin)
    self.usdc = IERC20(usdc_addr)
    self.pool = pool_addr
    self.reserve_target = _target
    self.base_retention_bps = _base_retention
    self.max_retention_bps = _max_retention


# Core

@external
def deposit(amount: uint256):
    """
    @notice Notify reserve of incoming premium retention.
    @dev    Pool transfers USDC directly to this contract's address
            before calling deposit(). This avoids the approve+transferFrom
            pattern and saves gas.
    """
    assert msg.sender == self.pool, "not pool"
    log ReserveDeposited(amount=amount)


@external
def cover_loss(amount: uint256) -> uint256:
    """
    @notice Cover losses from reserve. Returns amount actually covered.
    """
    assert msg.sender == self.pool, "not pool"
    bal: uint256 = staticcall self.usdc.balanceOf(self)
    covered: uint256 = min(amount, bal)
    if covered > 0:
        extcall self.usdc.transfer(self.pool, covered)
        log LossCovered(amount=covered)
    return covered


@external
@view
def current_retention_bps() -> uint256:
    """
    @notice Dynamic retention rate. Linear interpolation:
            fully funded → base_retention, empty → max_retention.
    """
    bal: uint256 = staticcall self.usdc.balanceOf(self)
    if bal >= self.reserve_target or self.reserve_target == 0:
        return self.base_retention_bps
    if bal == 0:
        return self.max_retention_bps

    deficit: uint256 = self.reserve_target - bal
    spread: uint256 = self.max_retention_bps - self.base_retention_bps
    return self.base_retention_bps + (spread * deficit) // self.reserve_target


@external
@view
def reserve_balance() -> uint256:
    return staticcall self.usdc.balanceOf(self)


@external
@view
def is_healthy() -> bool:
    return staticcall self.usdc.balanceOf(self) >= self.reserve_target


# Admin

@external
def set_reserve_target(target: uint256):
    ownable._check_owner()
    self.reserve_target = target


@external
def set_retention_bps(base: uint256, _max: uint256):
    ownable._check_owner()
    assert _max >= base, "max must be >= base"
    self.base_retention_bps = base
    self.max_retention_bps = _max


@external
def set_pool(new_pool: address):
    ownable._check_owner()
    self.pool = new_pool
