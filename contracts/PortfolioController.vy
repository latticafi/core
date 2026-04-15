# pragma version ~=0.4.0

"""
@title Lattica Portfolio Controller
@notice Enforces portfolio-level risk constraints: per-condition caps,
        per-cluster budgets, resolution-window concentration limits,
        and calibration-driven circuit breaker.
@dev    Cluster assignments are set by owner based on off-chain
        co-movement analysis updated each epoch.
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow

initializes: ownable
initializes: ow[ownable := ownable]

# Constants

BUCKET_SIZE: constant(uint256) = 7 * 86400  # 7 days

# Storage

pool: public(address)

# Per-condition
condition_exposure: public(HashMap[bytes32, uint256])
condition_cap: public(HashMap[bytes32, uint256])

# Per-cluster
condition_cluster: public(HashMap[bytes32, uint256])
cluster_exposure: public(HashMap[uint256, uint256])
cluster_budget: public(HashMap[uint256, uint256])

# Resolution window buckets
window_exposure: public(HashMap[uint256, uint256])
window_cap: public(HashMap[uint256, uint256])
default_window_cap: public(uint256)

# Global
total_exposure: public(uint256)
max_total_exposure: public(uint256)

# Circuit breaker
circuit_broken: public(bool)
realized_loss_ratio_bps: public(uint256)
circuit_breaker_threshold_bps: public(uint256)  # e.g. 20000 = 200%

# Constructor

@deploy
def __init__(pool_addr: address, owner: address, _max_total: uint256):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(owner)
    self.pool = pool_addr
    self.max_total_exposure = _max_total
    self.default_window_cap = max_value(uint256)
    self.circuit_breaker_threshold_bps = 20000  # 200%


# Core

@external
@view
def check_capacity(
    condition_id: bytes32, amount: uint256, epoch_end: uint256
) -> bool:
    if self.circuit_broken:
        return False
    if self.total_exposure + amount > self.max_total_exposure:
        return False

    cap: uint256 = self.condition_cap[condition_id]
    if cap > 0 and self.condition_exposure[condition_id] + amount > cap:
        return False

    cluster: uint256 = self.condition_cluster[condition_id]
    budget: uint256 = self.cluster_budget[cluster]
    if budget > 0 and self.cluster_exposure[cluster] + amount > budget:
        return False

    bucket: uint256 = epoch_end // BUCKET_SIZE
    w_cap: uint256 = self.window_cap[bucket]
    if w_cap == 0:
        w_cap = self.default_window_cap
    if self.window_exposure[bucket] + amount > w_cap:
        return False

    return True


@external
def record_origination(
    condition_id: bytes32, amount: uint256, epoch_end: uint256
):
    assert msg.sender == self.pool, "not pool"
    assert not self.circuit_broken, "circuit breaker active"

    self.total_exposure += amount
    assert self.total_exposure <= self.max_total_exposure, "total cap exceeded"

    self.condition_exposure[condition_id] += amount
    cap: uint256 = self.condition_cap[condition_id]
    if cap > 0:
        assert (
            self.condition_exposure[condition_id] <= cap
        ), "condition cap exceeded"

    cluster: uint256 = self.condition_cluster[condition_id]
    self.cluster_exposure[cluster] += amount
    budget: uint256 = self.cluster_budget[cluster]
    if budget > 0:
        assert (
            self.cluster_exposure[cluster] <= budget
        ), "cluster budget exceeded"

    bucket: uint256 = epoch_end // BUCKET_SIZE
    self.window_exposure[bucket] += amount


@external
def record_settlement(
    condition_id: bytes32, amount: uint256, loss: uint256, epoch_end: uint256
):
    assert msg.sender == self.pool, "not pool"

    if amount <= self.total_exposure:
        self.total_exposure -= amount
    else:
        self.total_exposure = 0

    if amount <= self.condition_exposure[condition_id]:
        self.condition_exposure[condition_id] -= amount
    else:
        self.condition_exposure[condition_id] = 0

    cluster: uint256 = self.condition_cluster[condition_id]
    if amount <= self.cluster_exposure[cluster]:
        self.cluster_exposure[cluster] -= amount
    else:
        self.cluster_exposure[cluster] = 0

    if epoch_end > 0:
        bucket: uint256 = epoch_end // BUCKET_SIZE
        if amount <= self.window_exposure[bucket]:
            self.window_exposure[bucket] -= amount
        else:
            self.window_exposure[bucket] = 0


@external
@view
def is_circuit_broken() -> bool:
    return self.circuit_broken


# Owner

@external
def set_condition_cap(condition_id: bytes32, cap: uint256):
    ownable._check_owner()
    self.condition_cap[condition_id] = cap


@external
def set_cluster_assignment(condition_id: bytes32, cluster_id: uint256):
    ownable._check_owner()
    self.condition_cluster[condition_id] = cluster_id


@external
def set_cluster_budget(cluster_id: uint256, budget: uint256):
    ownable._check_owner()
    self.cluster_budget[cluster_id] = budget


@external
def set_window_cap(bucket: uint256, cap: uint256):
    ownable._check_owner()
    self.window_cap[bucket] = cap


@external
def set_default_window_cap(cap: uint256):
    ownable._check_owner()
    self.default_window_cap = cap


@external
def set_max_total_exposure(_max: uint256):
    ownable._check_owner()
    self.max_total_exposure = _max


@external
def set_circuit_breaker(broken: bool):
    ownable._check_owner()
    self.circuit_broken = broken


@external
def update_calibration(realized_bps: uint256, predicted_bps: uint256):
    """
    @notice Called by owner at epoch settlement with calibration data.
            Auto-trips circuit breaker if realized >> predicted.
    """
    ownable._check_owner()
    if predicted_bps > 0:
        self.realized_loss_ratio_bps = (realized_bps * 10000) // predicted_bps
        if self.realized_loss_ratio_bps > self.circuit_breaker_threshold_bps:
            self.circuit_broken = True
