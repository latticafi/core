# pragma version ~=0.4.3

from snekmate.auth import ownable_2step
from snekmate.auth import ownable

initializes: ownable
initializes: ownable_2step[ownable := ownable]

exports: (
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
    ownable.owner,
    ownable_2step.pending_owner,
)


struct MarketParams:
    collateral_factor: uint256
    max_exposure_cap: uint256
    min_liquidity_depth: uint256
    resolution_time: uint256
    cutoff: uint256
    is_active: bool
    is_paused: bool


event MarketOnboarded:
    condition_id: bytes32
    resolution_time: uint256
    cutoff: uint256


event MarketPaused:
    condition_id: bytes32


event MarketUnpaused:
    condition_id: bytes32


event MarketDeboarded:
    condition_id: bytes32


event CollateralFactorUpdated:
    condition_id: bytes32
    new_factor: uint256


event ExposureCapUpdated:
    condition_id: bytes32
    new_cap: uint256


CUTOFF_BUFFER: constant(uint256) = 14400

markets: HashMap[bytes32, MarketParams]
market_list: DynArray[bytes32, 4096]
market_count: public(uint256)


@deploy
def __init__():
    ownable.__init__()
    ownable_2step.__init__()


@internal
@view
def _assert_registered(condition_id: bytes32):
    assert (
        self.markets[condition_id].resolution_time != 0
    ), "market not registered"


@external
def onboard_market(
    condition_id: bytes32,
    resolution_time: uint256,
    collateral_factor: uint256,
    max_exposure_cap: uint256,
    min_liquidity_depth: uint256,
):
    ownable._check_owner()
    assert (
        self.markets[condition_id].resolution_time == 0
    ), "market already registered"
    assert (
        resolution_time > block.timestamp + CUTOFF_BUFFER
    ), "resolution too soon"
    assert collateral_factor <= 10000, "collateral factor exceeds max"

    cutoff: uint256 = resolution_time - CUTOFF_BUFFER

    self.markets[condition_id] = MarketParams(
        collateral_factor=collateral_factor,
        max_exposure_cap=max_exposure_cap,
        min_liquidity_depth=min_liquidity_depth,
        resolution_time=resolution_time,
        cutoff=cutoff,
        is_active=True,
        is_paused=False,
    )
    self.market_list.append(condition_id)
    self.market_count += 1

    log MarketOnboarded(
        condition_id=condition_id,
        resolution_time=resolution_time,
        cutoff=cutoff,
    )


@external
def pause_market(condition_id: bytes32):
    ownable._check_owner()
    self._assert_registered(condition_id)
    assert self.markets[condition_id].is_active, "market not active"
    self.markets[condition_id].is_paused = True
    log MarketPaused(condition_id=condition_id)


@external
def unpause_market(condition_id: bytes32):
    ownable._check_owner()
    self._assert_registered(condition_id)
    self.markets[condition_id].is_paused = False
    log MarketUnpaused(condition_id=condition_id)


@external
def deboard_market(condition_id: bytes32):
    ownable._check_owner()
    self._assert_registered(condition_id)
    self.markets[condition_id].is_active = False
    log MarketDeboarded(condition_id=condition_id)


@external
@view
def is_registered(condition_id: bytes32) -> bool:
    return self.markets[condition_id].resolution_time != 0


@external
@view
def get_market_params(condition_id: bytes32) -> MarketParams:
    self._assert_registered(condition_id)
    return self.markets[condition_id]


@external
@view
def get_cutoff(condition_id: bytes32) -> uint256:
    self._assert_registered(condition_id)
    return self.markets[condition_id].cutoff


@external
def update_collateral_factor(condition_id: bytes32, new_factor: uint256):
    ownable._check_owner()
    self._assert_registered(condition_id)
    assert new_factor <= 10000, "collateral factor exceeds max"
    self.markets[condition_id].collateral_factor = new_factor
    log CollateralFactorUpdated(
        condition_id=condition_id, new_factor=new_factor
    )


@external
def update_max_exposure_cap(condition_id: bytes32, new_cap: uint256):
    ownable._check_owner()
    self._assert_registered(condition_id)
    self.markets[condition_id].max_exposure_cap = new_cap
    log ExposureCapUpdated(condition_id=condition_id, new_cap=new_cap)
