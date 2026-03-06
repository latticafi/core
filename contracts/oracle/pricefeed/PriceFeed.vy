# pragma version ~=0.4.3

from snekmate.auth import ownable

initializes: ownable

exports: (
    ownable.transfer_ownership,
    ownable.renounce_ownership,
    ownable.owner,
)

event PriceUpdated:
    condition_id: bytes32
    price: uint256
    timestamp: uint256

event CircuitBreakerTripped:
    condition_id: bytes32
    price: uint256
    timestamp: uint256

MAX_PRICE: constant(uint256) = 10 ** 18
MAX_BPS: constant(uint256) = 10000

condition_id: public(bytes32)
price: public(uint256)
last_update: public(uint256)
prev_price: public(uint256)
prev_update: public(uint256)
circuit_breaker_tripped: public(bool)
circuit_breaker_reset_time: public(uint256)
authorized_updater: public(address)

deviation_threshold_bps: public(uint256)
staleness_limit: public(uint256)
circuit_breaker_threshold_bps: public(uint256)
circuit_breaker_cooldown: public(uint256)

@deploy
def __init__(
    _condition_id: bytes32,
    _authorized_updater: address,
    _deviation_threshold_bps: uint256,
    _staleness_limit: uint256,
    _circuit_breaker_threshold_bps: uint256,
    _circuit_breaker_cooldown: uint256,
):
    ownable.__init__()
    self.condition_id = _condition_id
    self.authorized_updater = _authorized_updater
    self.deviation_threshold_bps = _deviation_threshold_bps
    self.staleness_limit = _staleness_limit
    self.circuit_breaker_threshold_bps = _circuit_breaker_threshold_bps
    self.circuit_breaker_cooldown = _circuit_breaker_cooldown

@external
def push_price(new_price: uint256):
    assert msg.sender == self.authorized_updater, "unauthorized"
    assert new_price <= MAX_PRICE, "price out of range"

    if self.circuit_breaker_tripped:
        if block.timestamp < self.circuit_breaker_reset_time:
            raise "circuit breaker active"
        self.circuit_breaker_tripped = False

    if self.price > 0:
        diff: uint256 = 0
        if new_price >= self.price:
            diff = new_price - self.price
        else:
            diff = self.price - new_price
        deviation: uint256 = (diff * MAX_BPS) // self.price
        assert deviation >= self.deviation_threshold_bps, "deviation too small"

        if deviation >= self.circuit_breaker_threshold_bps:
            self.circuit_breaker_tripped = True
            self.circuit_breaker_reset_time = block.timestamp + self.circuit_breaker_cooldown
            log CircuitBreakerTripped(
                condition_id=self.condition_id,
                price=new_price,
                timestamp=block.timestamp,
            )

    self.prev_price = self.price
    self.prev_update = self.last_update
    self.price = new_price
    self.last_update = block.timestamp

    log PriceUpdated(
        condition_id=self.condition_id,
        price=new_price,
        timestamp=block.timestamp,
    )

@view
@external
def get_price() -> (uint256, bool):
    is_stale: bool = True
    if self.last_update > 0:
        is_stale = (block.timestamp - self.last_update) > self.staleness_limit
    return (self.price, is_stale)

@view
@external
def is_circuit_breaker_active() -> bool:
    return self.circuit_breaker_tripped and block.timestamp < self.circuit_breaker_reset_time
