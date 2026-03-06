# pragma version ~=0.4.3

from snekmate.auth import access_control

initializes: access_control

exports: (
    access_control.hasRole,
    access_control.getRoleAdmin,
    access_control.grantRole,
    access_control.revokeRole,
    access_control.renounceRole,
    access_control.set_role_admin,
    access_control.supportsInterface,
    access_control.DEFAULT_ADMIN_ROLE,
)

interface IERC20:
    def transfer(_to: address, _amount: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _amount: uint256) -> bool: nonpayable
    def balanceOf(_account: address) -> uint256: view

interface ICollateralManager:
    def deposit_collateral(_borrower: address, _amount: uint256, _token_id: uint256): nonpayable
    def release_collateral(_borrower: address): nonpayable
    def set_debt(_borrower: address, _debt: uint256): nonpayable
    def get_health_factor(_borrower: address) -> uint256: view

interface IPremiumOracle:
    def verify_and_consume(_borrower: address, _premium_bps: uint256, _amount: uint256, _deadline: uint256, _signature: Bytes[65]) -> uint256: nonpayable

interface IInterestRateModel:
    def get_rate(_utilization_bps: uint256) -> uint256: view

interface IPriceFeed:
    def get_price() -> (uint256, bool): view
    def is_circuit_breaker_active() -> bool: view

interface IMarketRegistry:
    def get_market_params(_condition_id: bytes32) -> (uint256, uint256, uint256, uint256, uint256, bool, bool): view
    def get_cutoff(_condition_id: bytes32) -> uint256: view

flag PoolState:
    OPEN
    PAUSED
    CUTOFF

struct Loan:
    principal: uint256
    interest_paid: uint256
    premium_paid: uint256
    rate_bps: uint256
    epoch_end: uint256
    is_active: bool

event Deposit:
    lender: address
    amount: uint256
    shares: uint256

event Withdraw:
    lender: address
    amount: uint256
    shares: uint256

event Borrow:
    borrower: address
    amount: uint256
    interest: uint256
    premium: uint256
    rate_bps: uint256
    duration: uint256

event Repay:
    borrower: address
    amount: uint256

event LiquidationSettled:
    borrower: address
    recovered: uint256

event ShortfallCovered:
    borrower: address
    shortfall: uint256

event LoanDurationBoundsUpdated:
    min_duration: uint256
    max_duration: uint256

LIQUIDATOR_ROLE: constant(bytes32) = keccak256("LIQUIDATOR_ROLE")
MAX_BPS: constant(uint256) = 10000

condition_id: public(bytes32)
usdc_e: public(address)
collateral_manager: public(address)
premium_oracle: public(address)
interest_rate_model: public(address)
market_registry: public(address)
price_feed: public(address)
total_deposits: public(uint256)
total_borrowed: public(uint256)
premium_reserve: public(uint256)
shares: public(HashMap[address, uint256])
total_shares: public(uint256)
loans: public(HashMap[address, Loan])
min_loan_duration: public(uint256)
max_loan_duration: public(uint256)
pool_state: public(PoolState)


@deploy
def __init__(
    _condition_id: bytes32,
    _usdc_e: address,
    _collateral_manager: address,
    _premium_oracle: address,
    _interest_rate_model: address,
    _market_registry: address,
    _price_feed: address,
    _min_loan_duration: uint256,
    _max_loan_duration: uint256,
):
    access_control.__init__()
    assert _usdc_e != empty(address), "empty usdc_e"
    assert _collateral_manager != empty(address), "empty collateral_manager"
    assert _premium_oracle != empty(address), "empty premium_oracle"
    assert _interest_rate_model != empty(address), "empty interest_rate_model"
    assert _market_registry != empty(address), "empty market_registry"
    assert _price_feed != empty(address), "empty price_feed"
    assert _min_loan_duration > 0, "zero min_loan_duration"
    assert _max_loan_duration >= _min_loan_duration, "max < min duration"
    self.condition_id = _condition_id
    self.usdc_e = _usdc_e
    self.collateral_manager = _collateral_manager
    self.premium_oracle = _premium_oracle
    self.interest_rate_model = _interest_rate_model
    self.market_registry = _market_registry
    self.price_feed = _price_feed
    self.min_loan_duration = _min_loan_duration
    self.max_loan_duration = _max_loan_duration
    self.pool_state = PoolState.OPEN


@nonreentrant
@external
def deposit(amount: uint256):
    assert amount > 0, "zero amount"
    assert (
        self.pool_state == PoolState.OPEN
        or self.pool_state == PoolState.PAUSED
    ), "deposits disabled"
    extcall IERC20(self.usdc_e).transferFrom(msg.sender, self, amount)
    new_shares: uint256 = 0
    if self.total_shares == 0:
        new_shares = amount
    else:
        new_shares = (amount * self.total_shares) // self.total_deposits
    self.shares[msg.sender] += new_shares
    self.total_shares += new_shares
    self.total_deposits += amount
    log Deposit(lender=msg.sender, amount=amount, shares=new_shares)


@nonreentrant
@external
def withdraw(share_amount: uint256):
    assert share_amount > 0, "zero shares"
    assert self.shares[msg.sender] >= share_amount, "insufficient shares"
    value: uint256 = (share_amount * self.total_deposits) // self.total_shares
    available: uint256 = self.total_deposits - self.total_borrowed
    assert value <= available, "insufficient liquidity"
    self.shares[msg.sender] -= share_amount
    self.total_shares -= share_amount
    self.total_deposits -= value
    extcall IERC20(self.usdc_e).transfer(msg.sender, value)
    log Withdraw(lender=msg.sender, amount=value, shares=share_amount)


@nonreentrant
@external
def borrow(amount: uint256, borrower: address, duration: uint256, premium_bps: uint256, deadline: uint256, signature: Bytes[65]):
    assert self.pool_state == PoolState.OPEN, "not open"
    assert amount > 0, "zero amount"
    assert not self.loans[borrower].is_active, "loan exists"
    assert duration >= self.min_loan_duration, "duration too short"
    assert duration <= self.max_loan_duration, "duration too long"

    cutoff: uint256 = staticcall IMarketRegistry(self.market_registry).get_cutoff(
        self.condition_id
    )
    assert block.timestamp < cutoff, "past cutoff"

    params: (uint256, uint256, uint256, uint256, uint256, bool, bool) = staticcall IMarketRegistry(
        self.market_registry
    ).get_market_params(self.condition_id)
    assert params[5], "market not active"
    assert not params[6], "market paused"
    assert self.total_borrowed + amount <= params[1], "exposure cap exceeded"

    price: uint256 = 0
    is_stale: bool = False
    price, is_stale = staticcall IPriceFeed(self.price_feed).get_price()
    assert not is_stale, "price is stale"
    assert price > 0, "no price"
    assert not staticcall IPriceFeed(self.price_feed).is_circuit_breaker_active(), "circuit breaker active"

    available: uint256 = self.total_deposits - self.total_borrowed
    assert amount <= available, "insufficient liquidity"

    new_borrowed: uint256 = self.total_borrowed + amount
    utilization: uint256 = (new_borrowed * MAX_BPS) // self.total_deposits
    rate_bps: uint256 = staticcall IInterestRateModel(self.interest_rate_model).get_rate(
        utilization
    )
    interest: uint256 = (amount * rate_bps) // MAX_BPS

    verified_premium_bps: uint256 = extcall IPremiumOracle(self.premium_oracle).verify_and_consume(
        borrower, premium_bps, amount, deadline, signature
    )
    premium: uint256 = (amount * verified_premium_bps) // MAX_BPS

    net: uint256 = amount - interest - premium
    assert net > 0, "net zero"

    self.total_borrowed += amount
    self.total_deposits += interest
    self.premium_reserve += premium

    epoch_end: uint256 = block.timestamp + duration
    if epoch_end > cutoff:
        epoch_end = cutoff

    self.loans[borrower] = Loan(
        principal=amount,
        interest_paid=interest,
        premium_paid=premium,
        rate_bps=rate_bps,
        epoch_end=epoch_end,
        is_active=True,
    )

    extcall ICollateralManager(self.collateral_manager).set_debt(borrower, amount)
    health: uint256 = staticcall ICollateralManager(self.collateral_manager).get_health_factor(borrower)
    assert health >= 10000, "undercollateralized"

    extcall IERC20(self.usdc_e).transfer(borrower, net)
    log Borrow(
        borrower=borrower,
        amount=amount,
        interest=interest,
        premium=premium,
        rate_bps=rate_bps,
        duration=duration,
    )


@nonreentrant
@external
def repay(borrower: address):
    loan: Loan = self.loans[borrower]
    assert loan.is_active, "no active loan"
    self.total_borrowed -= loan.principal
    self.loans[borrower].is_active = False
    extcall IERC20(self.usdc_e).transferFrom(msg.sender, self, loan.principal)
    extcall ICollateralManager(self.collateral_manager).release_collateral(borrower)
    log Repay(borrower=borrower, amount=loan.principal)


@nonreentrant
@external
def handle_liquidation_proceeds(borrower: address, recovered: uint256):
    access_control._check_role(LIQUIDATOR_ROLE, msg.sender)
    loan: Loan = self.loans[borrower]
    assert loan.is_active, "no active loan"
    self.loans[borrower].is_active = False
    self.total_borrowed -= loan.principal
    extcall IERC20(self.usdc_e).transferFrom(msg.sender, self, recovered)
    if recovered < loan.principal:
        shortfall: uint256 = loan.principal - recovered
        if self.premium_reserve >= shortfall:
            self.premium_reserve -= shortfall
        else:
            self.total_deposits -= (shortfall - self.premium_reserve)
            self.premium_reserve = 0
    log LiquidationSettled(borrower=borrower, recovered=recovered)


@external
def cover_shortfall(borrower: address, shortfall: uint256):
    access_control._check_role(LIQUIDATOR_ROLE, msg.sender)
    if self.premium_reserve >= shortfall:
        self.premium_reserve -= shortfall
    else:
        self.total_deposits -= (shortfall - self.premium_reserve)
        self.premium_reserve = 0
    log ShortfallCovered(borrower=borrower, shortfall=shortfall)


@view
@external
def get_share_value(share_amount: uint256) -> uint256:
    if self.total_shares == 0:
        return 0
    return (share_amount * self.total_deposits) // self.total_shares


@external
def set_loan_duration_bounds(min_duration: uint256, max_duration: uint256):
    access_control._check_role(access_control.DEFAULT_ADMIN_ROLE, msg.sender)
    assert min_duration > 0, "zero min_duration"
    assert max_duration >= min_duration, "max < min duration"
    self.min_loan_duration = min_duration
    self.max_loan_duration = max_duration
    log LoanDurationBoundsUpdated(min_duration=min_duration, max_duration=max_duration)


@external
def pause():
    access_control._check_role(access_control.DEFAULT_ADMIN_ROLE, msg.sender)
    self.pool_state = PoolState.PAUSED


@external
def unpause():
    access_control._check_role(access_control.DEFAULT_ADMIN_ROLE, msg.sender)
    self.pool_state = PoolState.OPEN
