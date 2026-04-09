# pragma version ~=0.4.0

"""
@title Lattica Price Feed
@notice Receives off-chain price updates for prediction market positions.
        Enforces minimum deviation threshold and circuit breaker on large jumps.
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow

initializes: ownable
initializes: ow[ownable := ownable]

# Storage

struct PriceData:
    current_price: uint256  # 18 decimals, [0, 1e18]
    previous_price: uint256
    current_timestamp: uint256
    previous_timestamp: uint256
    circuit_breaker_until: uint256  # paused until this timestamp


updater: public(address)
min_deviation: public(uint256)  # min absolute change in 1e18
circuit_breaker_threshold: public(uint256)  # max single update change
circuit_breaker_cooldown: public(uint256)  # cooldown period in seconds

prices: public(HashMap[bytes32, PriceData])

# Events

event PriceUpdated:
    condition_id: indexed(bytes32)
    price: uint256
    timestamp: uint256


event CircuitBreakerTripped:
    condition_id: indexed(bytes32)
    old_price: uint256
    new_price: uint256


# Constructor

@deploy
def __init__(
    _updater: address,
    admin: address,
    _min_deviation: uint256,
    _cb_threshold: uint256,
    _cb_cooldown: uint256,
):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(admin)
    self.updater = _updater
    self.min_deviation = _min_deviation
    self.circuit_breaker_threshold = _cb_threshold
    self.circuit_breaker_cooldown = _cb_cooldown


# Core

@external
def update_price(condition_id: bytes32, price: uint256):
    assert msg.sender == self.updater, "not updater"
    assert price <= 10**18, "invalid price"

    pd: PriceData = self.prices[condition_id]
    assert block.timestamp >= pd.circuit_breaker_until, "circuit breaker active"

    current: uint256 = pd.current_price

    # Filter noise (skip if first update)
    if current > 0:
        delta: uint256 = 0
        if price > current:
            delta = price - current
        else:
            delta = current - price

        assert delta >= self.min_deviation, "below min deviation"

        # Reject update entirely if move is too large
        if delta > self.circuit_breaker_threshold:
            self.prices[condition_id].circuit_breaker_until = (
                block.timestamp + self.circuit_breaker_cooldown
            )
            log CircuitBreakerTripped(condition_id, current, price)
            return  # price NOT stored — old price remains current
    self.prices[condition_id].previous_price = current
    self.prices[condition_id].previous_timestamp = pd.current_timestamp
    self.prices[condition_id].current_price = price
    self.prices[condition_id].current_timestamp = block.timestamp

    log PriceUpdated(condition_id, price, block.timestamp)


@external
@view
def get_price(condition_id: bytes32) -> (uint256, uint256):
    pd: PriceData = self.prices[condition_id]
    return (pd.current_price, pd.current_timestamp)


@external
@view
def is_circuit_broken(condition_id: bytes32) -> bool:
    return block.timestamp < self.prices[condition_id].circuit_breaker_until


# Admin

@external
def reset_circuit_breaker(condition_id: bytes32):
    ownable._check_owner()
    self.prices[condition_id].circuit_breaker_until = 0


@external
def set_updater(new_updater: address):
    ownable._check_owner()
    self.updater = new_updater


@external
def set_circuit_breaker_params(threshold: uint256, cooldown: uint256):
    ownable._check_owner()
    self.circuit_breaker_threshold = threshold
    self.circuit_breaker_cooldown = cooldown
