# pragma version ~=0.4.0

"""
@title Lattica Factory
@author Lattica Protocol
@license MIT
@notice Deployment coordinator. Deploys one pool stack from EIP-5202
        blueprints and wires all contracts together atomically.
        NOT a multi-pool registry. Lattica is a single-pool protocol.
"""

from interfaces import ILendingPool as ILendingPool
from interfaces import IPoolCore as IPoolCore


# Interfaces

# Storage — Ownership

admin: public(address)
future_admin: public(address)

# Blueprint addresses
pool_blueprint: public(address)
core_blueprint: public(address)
oracle_blueprint: public(address)
price_feed_blueprint: public(address)
controller_blueprint: public(address)
reserve_blueprint: public(address)
liquidator_blueprint: public(address)

# Shared
usdc: public(address)
ctf_token: public(address)

# Deployed addresses (one set — single pool)
pool: public(address)
core: public(address)
oracle: public(address)
price_feed: public(address)
controller: public(address)
reserve: public(address)
liquidator: public(address)
views: public(address)

deployed: public(bool)

# Default parameters
default_reserve_target: public(uint256)
default_base_retention_bps: public(uint256)
default_max_retention_bps: public(uint256)
default_max_exposure: public(uint256)

# Events

event PoolStackDeployed:
    pool: address
    core: address
    oracle: address
    price_feed: address
    controller: address
    reserve: address
    liquidator: address


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
    self.default_max_exposure = 10_000_000 * 10**6


# Deploy

@external
def deploy_pool(
    _pricer: address,
    _oracle_signer: address,
    _liquidator_operator: address,
    _guardian: address,
):
    assert msg.sender == self.admin, "not admin"
    assert not self.deployed, "already deployed"
    assert self.pool_blueprint != empty(address), "set blueprints first"
    assert self.core_blueprint != empty(address), "set blueprints first"
    assert self.oracle_blueprint != empty(address), "set blueprints first"
    assert self.price_feed_blueprint != empty(address), "set blueprints first"
    assert self.controller_blueprint != empty(address), "set blueprints first"
    assert self.reserve_blueprint != empty(address), "set blueprints first"
    assert self.liquidator_blueprint != empty(address), "set blueprints first"

    # 1. Deploy LendingPool
    _pool: address = create_from_blueprint(
        self.pool_blueprint,
        self.usdc,
        self.ctf_token,
        self.admin,
        code_offset=3,
    )

    # 2. Deploy PriceFeed (no dependencies)
    _min_dev: uint256 = 10**14
    _cb_thresh: uint256 = 2 * 10**17
    _cb_cool: uint256 = 3600
    _price_feed: address = create_from_blueprint(
        self.price_feed_blueprint,
        _oracle_signer,
        self.admin,
        _min_dev,
        _cb_thresh,
        _cb_cool,
        code_offset=3,
    )

    # 3. Deploy PoolCore (oracle + controller wired later)
    _core: address = create_from_blueprint(
        self.core_blueprint,
        self.usdc,
        _pool,
        _price_feed,
        self.admin,
        code_offset=3,
    )

    # 4. Deploy PremiumOracle (pool = PoolCore — PoolCore calls verify_quote)
    _oracle: address = create_from_blueprint(
        self.oracle_blueprint,
        _pricer,
        _core,
        self.admin,
        code_offset=3,
    )

    # 5. Deploy PortfolioController (pool = PoolCore — PoolCore calls record_*)
    _controller: address = create_from_blueprint(
        self.controller_blueprint,
        _core,
        self.admin,
        self.default_max_exposure,
        code_offset=3,
    )

    # 6. Wire PoolCore to Oracle + Controller
    extcall IPoolCore(_core).set_peripherals(_oracle, _controller)

    # 7. Deploy Reserve (pool = LendingPool — LendingPool calls deposit/cover_loss)
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

    # 8. Deploy Liquidator (pool = LendingPool)
    _liquidator: address = create_from_blueprint(
        self.liquidator_blueprint,
        _pool,
        _liquidator_operator,
        self.ctf_token,
        self.admin,
        code_offset=3,
    )

    # 9. Wire LendingPool
    extcall ILendingPool(_pool).initialize(
        _core, _liquidator, _reserve, _price_feed, _guardian
    )

    # Store
    self.pool = _pool
    self.core = _core
    self.oracle = _oracle
    self.price_feed = _price_feed
    self.controller = _controller
    self.reserve = _reserve
    self.liquidator = _liquidator
    self.deployed = True

    log PoolStackDeployed(
        pool=_pool,
        core=_core,
        oracle=_oracle,
        price_feed=_price_feed,
        controller=_controller,
        reserve=_reserve,
        liquidator=_liquidator,
    )


# Blueprint setters (pre-deploy only)

@external
def set_blueprints(
    _pool: address,
    _core: address,
    _oracle: address,
    _price_feed: address,
    _controller: address,
    _reserve: address,
    _liquidator: address,
):
    assert msg.sender == self.admin, "not admin"
    assert not self.deployed, "already deployed"
    self.pool_blueprint = _pool
    self.core_blueprint = _core
    self.oracle_blueprint = _oracle
    self.price_feed_blueprint = _price_feed
    self.controller_blueprint = _controller
    self.reserve_blueprint = _reserve
    self.liquidator_blueprint = _liquidator


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
