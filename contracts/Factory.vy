# pragma version ~=0.4.0

"""
@title Lattica Factory
@author Lattica Protocol
@license MIT
@notice Deployment coordinator. Deploys one pool stack from EIP-5202
        blueprints and wires all contracts together atomically.
"""

from interfaces import ILendingPool as ILendingPool
from interfaces import IPoolCore as IPoolCore

# Storage — Ownership

admin: public(address)
future_admin: public(address)

# Blueprint addresses
pool_blueprint: public(address)
core_blueprint: public(address)
oracle_blueprint: public(address)
controller_blueprint: public(address)
reserve_blueprint: public(address)

# Shared
usdc: public(address)
ctf_token: public(address)

# Deployed addresses (one set — single pool)
pool: public(address)
core: public(address)
oracle: public(address)
controller: public(address)
reserve: public(address)
views: public(address)

deployed: public(bool)

# Default parameters
default_reserve_target: public(uint256)
default_base_retention_bps: public(uint256)
default_max_retention_bps: public(uint256)
default_max_total_exposure: public(uint256)

# Events

event PoolStackDeployed:
    pool: address
    core: address
    oracle: address
    controller: address
    reserve: address


event TransferOwnershipCommitted:
    future_admin: indexed(address)


event TransferOwnershipAccepted:
    admin: indexed(address)


# Constructor

@deploy
def __init__(_admin: address, _usdc: address, _ctf_token: address):
    self.admin = _admin
    self.usdc = _usdc
    self.ctf_token = _ctf_token

    self.default_reserve_target = 100_000 * 10**6
    self.default_base_retention_bps = 1000
    self.default_max_retention_bps = 5000
    self.default_max_total_exposure = 10_000_000 * 10**6


# Deploy

@external
def deploy_pool(
    _pricer: address,
    _oracle_signer: address,
    _guardian: address,
):
    assert msg.sender == self.admin, "not admin"
    assert not self.deployed, "already deployed"
    assert self.pool_blueprint != empty(address), "set blueprints first"
    assert self.core_blueprint != empty(address), "set blueprints first"
    assert self.oracle_blueprint != empty(address), "set blueprints first"
    assert self.controller_blueprint != empty(address), "set blueprints first"
    assert self.reserve_blueprint != empty(address), "set blueprints first"

    # 1. LendingPool
    _pool: address = create_from_blueprint(
        self.pool_blueprint,
        self.usdc,
        self.ctf_token,
        self.admin,
        code_offset=3,
    )

    # 2. PoolCore
    _core: address = create_from_blueprint(
        self.core_blueprint,
        self.usdc,
        _pool,
        self.admin,
        code_offset=3,
    )

    # 3. PremiumOracle (pool = PoolCore)
    _oracle: address = create_from_blueprint(
        self.oracle_blueprint,
        _pricer,
        _core,
        self.admin,
        code_offset=3,
    )

    # 4. PortfolioController (pool = PoolCore)
    _controller: address = create_from_blueprint(
        self.controller_blueprint,
        _core,
        self.admin,
        self.default_max_total_exposure,
        code_offset=3,
    )

    # 5. Wire PoolCore
    extcall IPoolCore(_core).set_peripherals(_oracle, _controller)

    # 6. Reserve (pool = LendingPool)
    _reserve: address = create_from_blueprint(
        self.reserve_blueprint,
        self.usdc,
        _pool,
        self.admin,
        self.default_reserve_target,
        self.default_base_retention_bps,
        self.default_max_retention_bps,
        code_offset=3,
    )

    # 7. Wire LendingPool
    extcall ILendingPool(_pool).initialize(
        _core, _reserve, _oracle_signer, _guardian
    )

    # Store
    self.pool = _pool
    self.core = _core
    self.oracle = _oracle
    self.controller = _controller
    self.reserve = _reserve
    self.deployed = True

    log PoolStackDeployed(
        pool=_pool,
        core=_core,
        oracle=_oracle,
        controller=_controller,
        reserve=_reserve,
    )


# Blueprint setters

@external
def set_blueprints(
    _pool: address,
    _core: address,
    _oracle: address,
    _controller: address,
    _reserve: address,
):
    assert msg.sender == self.admin, "not admin"
    assert not self.deployed, "already deployed"
    self.pool_blueprint = _pool
    self.core_blueprint = _core
    self.oracle_blueprint = _oracle
    self.controller_blueprint = _controller
    self.reserve_blueprint = _reserve


@external
def set_views(_views: address):
    assert msg.sender == self.admin, "not admin"
    self.views = _views


# Ownership

@external
def commit_transfer_ownership(_future_admin: address):
    assert msg.sender == self.admin, "not admin"
    self.future_admin = _future_admin
    log TransferOwnershipCommitted(future_admin=_future_admin)


@external
def accept_transfer_ownership():
    assert msg.sender == self.future_admin, "not future admin"
    self.admin = self.future_admin
    self.future_admin = empty(address)
    log TransferOwnershipAccepted(admin=self.admin)
