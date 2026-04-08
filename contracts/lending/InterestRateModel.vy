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

MAX_BPS: constant(uint256) = 10000

base_rate_bps: public(uint256)
optimal_utilization_bps: public(uint256)
slope1_bps: public(uint256)
slope2_bps: public(uint256)


event ParamsUpdated:
    base_rate_bps: uint256
    optimal_utilization_bps: uint256
    slope1_bps: uint256
    slope2_bps: uint256


@deploy
def __init__(
    _base_rate_bps: uint256,
    _optimal_utilization_bps: uint256,
    _slope1_bps: uint256,
    _slope2_bps: uint256,
):
    ownable.__init__()
    ownable_2step.__init__()
    self._validate_params(
        _base_rate_bps, _optimal_utilization_bps, _slope1_bps, _slope2_bps
    )
    self.base_rate_bps = _base_rate_bps
    self.optimal_utilization_bps = _optimal_utilization_bps
    self.slope1_bps = _slope1_bps
    self.slope2_bps = _slope2_bps


@external
@view
def get_rate(utilization_bps: uint256) -> uint256:
    assert utilization_bps <= MAX_BPS, "utilization > MAX_BPS"

    if utilization_bps <= self.optimal_utilization_bps:
        return (
            self.base_rate_bps + (utilization_bps * self.slope1_bps) // MAX_BPS
        )

    return (
        self.base_rate_bps
        + (self.optimal_utilization_bps * self.slope1_bps) // MAX_BPS
        + (
            (utilization_bps - self.optimal_utilization_bps) * self.slope2_bps
        ) // MAX_BPS
    )


@external
def set_params(
    _base_rate_bps: uint256,
    _optimal_utilization_bps: uint256,
    _slope1_bps: uint256,
    _slope2_bps: uint256,
):
    ownable._check_owner()
    self._validate_params(
        _base_rate_bps, _optimal_utilization_bps, _slope1_bps, _slope2_bps
    )
    self.base_rate_bps = _base_rate_bps
    self.optimal_utilization_bps = _optimal_utilization_bps
    self.slope1_bps = _slope1_bps
    self.slope2_bps = _slope2_bps
    log ParamsUpdated(
        base_rate_bps=_base_rate_bps,
        optimal_utilization_bps=_optimal_utilization_bps,
        slope1_bps=_slope1_bps,
        slope2_bps=_slope2_bps,
    )


@internal
@pure
def _validate_params(
    _base_rate_bps: uint256,
    _optimal_utilization_bps: uint256,
    _slope1_bps: uint256,
    _slope2_bps: uint256,
):
    assert _base_rate_bps <= MAX_BPS, "base_rate > MAX_BPS"
    assert _optimal_utilization_bps <= MAX_BPS, "optimal_util > MAX_BPS"
    assert _slope1_bps <= MAX_BPS, "slope1 > MAX_BPS"
    assert _slope2_bps <= MAX_BPS, "slope2 > MAX_BPS"
