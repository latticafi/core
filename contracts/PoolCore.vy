# pragma version ~=0.4.0

"""
@title Lattica Pool Core
@author Lattica Protocol
@license MIT
@notice All lending state and business logic. Pure computation — never
        touches USDC, ERC1155, or Reserve. Only LendingPool calls this.
"""

from ethereum.ercs import IERC20
from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow

initializes: ownable
initializes: ow[ownable := ownable]

from interfaces import IPremiumOracle as IPremiumOracle
from interfaces import IPortfolioController as IPortfolioController

# Data Structures

struct MarketParams:
    token_id: uint256
    min_ltv_bps: uint256
    max_ltv_bps: uint256
    resolution_time: uint256
    origination_cutoff: uint256
    active: bool


struct Loan:
    borrower: address
    condition_id: bytes32
    token_id: uint256
    collateral_amount: uint256
    principal: uint256
    premium_paid: uint256
    interest_due: uint256
    interest_rate_bps: uint256
    liquidation_price: uint256
    epoch_start: uint256
    epoch_end: uint256
    repaid: bool
    liquidated: bool


# Constants

PRECISION: constant(uint256) = 10_000
YEAR: constant(uint256) = 365 * 86400
DEAD_SHARES: constant(uint256) = 1000

# Storage

pool: public(address)
usdc: public(IERC20)
oracle: public(address)
portfolio_controller: public(address)

total_shares: public(uint256)
share_balance: public(HashMap[address, uint256])

total_borrowed: public(uint256)
next_loan_id: public(uint256)
loans: public(HashMap[uint256, Loan])

markets: public(HashMap[bytes32, MarketParams])

base_rate_bps: public(uint256)
slope1_bps: public(uint256)
slope2_bps: public(uint256)
kink_bps: public(uint256)
maintenance_margin_bps: public(uint256)

# Events

event MarketOnboarded:
    condition_id: indexed(bytes32)
    token_id: uint256


event MarketPaused:
    condition_id: indexed(bytes32)


# Constructor

peripherals_set: bool


@deploy
def __init__(
    usdc_addr: address,
    pool_addr: address,
    owner: address,
):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(owner)
    self.usdc = IERC20(usdc_addr)
    self.pool = pool_addr

    self.base_rate_bps = 200
    self.slope1_bps = 1000
    self.slope2_bps = 10000
    self.kink_bps = 8000
    self.maintenance_margin_bps = 2000


@external
def set_peripherals(oracle_addr: address, controller_addr: address):
    """
    @notice One-time wiring called by Factory after Oracle and Controller deploy.
    """
    ownable._check_owner()
    assert not self.peripherals_set, "already set"
    assert oracle_addr != empty(address), "zero oracle"
    assert controller_addr != empty(address), "zero controller"
    self.oracle = oracle_addr
    self.portfolio_controller = controller_addr
    self.peripherals_set = True


@internal
def _only_pool():
    assert msg.sender == self.pool, "not pool"


# Share logic

@external
def deposit_shares(lender: address, amount: uint256) -> uint256:
    self._only_pool()
    assert amount > 0, "zero amount"

    shares: uint256 = 0
    if self.total_shares == 0:
        shares = amount - DEAD_SHARES
        assert shares > 0, "below minimum first deposit"
        self.total_shares = DEAD_SHARES + shares
        self.share_balance[lender] = shares
    else:
        shares = (amount * self.total_shares) // self._total_pool_value()
        assert shares > 0, "deposit too small"
        self.total_shares += shares
        self.share_balance[lender] += shares

    return shares


@external
def withdraw_shares(lender: address, shares: uint256) -> uint256:
    self._only_pool()
    assert shares > 0, "zero shares"
    assert self.share_balance[lender] >= shares, "insufficient shares"

    amount: uint256 = (shares * self._total_pool_value()) // self.total_shares
    assert amount <= self._available_liquidity(), "insufficient liquidity"

    self.total_shares -= shares
    self.share_balance[lender] -= shares
    return amount


# Origination — validates, creates loan, updates portfolio controller.
#               Price is trusted (already verified by LendingPool via PriceFeed).

@external
def originate(
    borrower: address,
    condition_id: bytes32,
    collateral_amount: uint256,
    borrow_amount: uint256,
    epoch_length: uint256,
    premium_bps: uint256,
    deadline: uint256,
    nonce: uint256,
    signature: Bytes[65],
    price: uint256,
) -> uint256:
    self._only_pool()

    assert self._is_eligible(condition_id), "market not eligible"
    market: MarketParams = self.markets[condition_id]

    epoch_end: uint256 = block.timestamp + epoch_length
    if market.resolution_time > 0:
        assert (
            epoch_end + market.origination_cutoff <= market.resolution_time
        ), "epoch overlaps resolution"

    valid: bool = extcall IPremiumOracle(self.oracle).verify_quote(
        borrower,
        condition_id,
        premium_bps,
        borrow_amount,
        collateral_amount,
        epoch_length,
        deadline,
        nonce,
        signature,
    )
    assert valid, "quote verification failed"

    has_capacity: bool = staticcall IPortfolioController(
        self.portfolio_controller
    ).check_capacity(condition_id, borrow_amount, epoch_end)
    assert has_capacity, "capacity exceeded"

    collateral_value: uint256 = (collateral_amount * price) // 10**18
    assert collateral_value > 0, "zero collateral value"

    ltv_bps: uint256 = (borrow_amount * PRECISION) // collateral_value
    assert ltv_bps >= market.min_ltv_bps, "below min LTV"
    assert ltv_bps <= market.max_ltv_bps, "above max LTV"

    liq_price: uint256 = (
        borrow_amount * (PRECISION + self.maintenance_margin_bps) * 10**18
    ) // (collateral_amount * PRECISION)
    assert liq_price < price, "liquidation price above current price"

    assert (
        borrow_amount <= self._available_liquidity()
    ), "insufficient liquidity"

    premium: uint256 = (borrow_amount * premium_bps) // PRECISION
    rate: uint256 = self._current_rate()
    interest: uint256 = (borrow_amount * rate * epoch_length) // (
        PRECISION * YEAR
    )

    loan_id: uint256 = self.next_loan_id
    self.next_loan_id = loan_id + 1

    self.loans[loan_id] = Loan(
        borrower=borrower,
        condition_id=condition_id,
        token_id=market.token_id,
        collateral_amount=collateral_amount,
        principal=borrow_amount,
        premium_paid=premium,
        interest_due=interest,
        interest_rate_bps=rate,
        liquidation_price=liq_price,
        epoch_start=block.timestamp,
        epoch_end=epoch_end,
        repaid=False,
        liquidated=False,
    )

    self.total_borrowed += borrow_amount

    extcall IPortfolioController(self.portfolio_controller).record_origination(
        condition_id, borrow_amount, epoch_end
    )

    return loan_id


# Settlement — updates state, does NOT move tokens.

@external
def settle_repay(loan_id: uint256, borrower: address) -> Loan:
    self._only_pool()
    loan: Loan = self.loans[loan_id]
    assert loan.borrower == borrower, "not borrower"
    assert not loan.repaid, "already repaid"
    assert not loan.liquidated, "already liquidated"
    assert block.timestamp <= loan.epoch_end, "epoch expired"

    self.loans[loan_id].repaid = True
    self.total_borrowed -= loan.principal

    extcall IPortfolioController(self.portfolio_controller).record_settlement(
        loan.condition_id, loan.principal, 0, loan.epoch_end
    )
    return loan


@external
def settle_roll(
    old_loan_id: uint256,
    borrower: address,
    epoch_length: uint256,
    premium_bps: uint256,
    deadline: uint256,
    nonce: uint256,
    signature: Bytes[65],
    price: uint256,
) -> (uint256, uint256, Loan):
    """
    @return (new_loan_id, total_cost, old_loan)
    """
    self._only_pool()

    old_loan: Loan = self.loans[old_loan_id]
    assert old_loan.borrower == borrower, "not borrower"
    assert not old_loan.repaid, "already repaid"
    assert not old_loan.liquidated, "already liquidated"
    assert block.timestamp <= old_loan.epoch_end, "epoch expired"

    condition_id: bytes32 = old_loan.condition_id
    borrow_amount: uint256 = old_loan.principal
    collateral_amount: uint256 = old_loan.collateral_amount

    assert self._is_eligible(condition_id), "market not eligible"
    market: MarketParams = self.markets[condition_id]

    epoch_end: uint256 = block.timestamp + epoch_length
    if market.resolution_time > 0:
        assert (
            epoch_end + market.origination_cutoff <= market.resolution_time
        ), "epoch overlaps resolution"

    valid: bool = extcall IPremiumOracle(self.oracle).verify_quote(
        borrower,
        condition_id,
        premium_bps,
        borrow_amount,
        collateral_amount,
        epoch_length,
        deadline,
        nonce,
        signature,
    )
    assert valid, "quote verification failed"

    has_capacity: bool = staticcall IPortfolioController(
        self.portfolio_controller
    ).check_capacity(condition_id, borrow_amount, epoch_end)
    assert has_capacity, "capacity exceeded"

    collateral_value: uint256 = (collateral_amount * price) // 10**18
    assert collateral_value > 0, "zero collateral value"
    ltv_bps: uint256 = (borrow_amount * PRECISION) // collateral_value
    assert ltv_bps >= market.min_ltv_bps, "below min LTV"
    assert ltv_bps <= market.max_ltv_bps, "above max LTV"

    liq_price: uint256 = (
        borrow_amount * (PRECISION + self.maintenance_margin_bps) * 10**18
    ) // (collateral_amount * PRECISION)
    assert liq_price < price, "liquidation price above current price"

    premium: uint256 = (borrow_amount * premium_bps) // PRECISION
    rate: uint256 = self._current_rate()
    interest: uint256 = (borrow_amount * rate * epoch_length) // (
        PRECISION * YEAR
    )
    total_cost: uint256 = premium + interest

    # Close old
    self.loans[old_loan_id].repaid = True
    extcall IPortfolioController(self.portfolio_controller).record_settlement(
        condition_id, borrow_amount, 0, old_loan.epoch_end
    )

    # Create new (total_borrowed unchanged — old out, new in)
    new_loan_id: uint256 = self.next_loan_id
    self.next_loan_id = new_loan_id + 1

    self.loans[new_loan_id] = Loan(
        borrower=borrower,
        condition_id=condition_id,
        token_id=market.token_id,
        collateral_amount=collateral_amount,
        principal=borrow_amount,
        premium_paid=premium,
        interest_due=interest,
        interest_rate_bps=rate,
        liquidation_price=liq_price,
        epoch_start=block.timestamp,
        epoch_end=epoch_end,
        repaid=False,
        liquidated=False,
    )

    extcall IPortfolioController(self.portfolio_controller).record_origination(
        condition_id, borrow_amount, epoch_end
    )

    return (new_loan_id, total_cost, old_loan)


@external
def mark_liquidated(loan_id: uint256) -> Loan:
    """
    @notice Mark loan as liquidated, update state + portfolio controller.
            Does NOT touch Reserve or move tokens — LendingPool handles that.
    """
    self._only_pool()
    loan: Loan = self.loans[loan_id]
    assert loan.borrower != empty(address), "loan does not exist"
    assert not loan.repaid, "already repaid"
    assert not loan.liquidated, "already liquidated"

    self.loans[loan_id].liquidated = True
    self.total_borrowed -= loan.principal

    extcall IPortfolioController(self.portfolio_controller).record_settlement(
        loan.condition_id, loan.principal, loan.principal, loan.epoch_end
    )
    return loan


# Market registry

@external
def set_market(condition_id: bytes32, params: MarketParams):
    ownable._check_owner()
    assert params.token_id != 0, "zero token id"
    assert (
        params.max_ltv_bps > params.min_ltv_bps
    ), "max LTV must exceed min LTV"
    assert params.max_ltv_bps <= 9500, "max LTV too high"
    is_new: bool = self.markets[condition_id].token_id == 0
    self.markets[condition_id] = params
    if is_new:
        log MarketOnboarded(condition_id=condition_id, token_id=params.token_id)


@external
def pause_market(condition_id: bytes32):
    ownable._check_owner()
    self.markets[condition_id].active = False
    log MarketPaused(condition_id=condition_id)


# Views

@external
@view
def health_factor(loan_id: uint256, price: uint256) -> uint256:
    return self._health_factor(loan_id, price)


@external
@view
def get_loan(loan_id: uint256) -> Loan:
    return self.loans[loan_id]


@external
@view
def share_price() -> uint256:
    if self.total_shares == 0:
        return 10**6
    return (self._total_pool_value() * 10**6) // self.total_shares


@external
@view
def current_rate() -> uint256:
    return self._current_rate()


@external
@view
def available_liquidity() -> uint256:
    return self._available_liquidity()


@external
@view
def utilization() -> uint256:
    total: uint256 = self._total_pool_value()
    if total == 0:
        return 0
    return (self.total_borrowed * PRECISION) // total


@external
@view
def total_assets() -> uint256:
    return self._total_pool_value()


@external
@view
def preview_liquidation_price(
    collateral_amount: uint256, borrow_amount: uint256
) -> uint256:
    assert collateral_amount > 0, "zero collateral"
    return (
        borrow_amount * (PRECISION + self.maintenance_margin_bps) * 10**18
    ) // (collateral_amount * PRECISION)


@external
@view
def get_liquidation_price(loan_id: uint256) -> uint256:
    return self.loans[loan_id].liquidation_price


@external
@view
def current_ltv(loan_id: uint256, price: uint256) -> uint256:
    loan: Loan = self.loans[loan_id]
    if loan.repaid or loan.liquidated:
        return 0
    collateral_value: uint256 = (loan.collateral_amount * price) // 10**18
    if collateral_value == 0:
        return PRECISION
    return (loan.principal * PRECISION) // collateral_value


@external
@view
def is_market_eligible(condition_id: bytes32) -> bool:
    return self._is_eligible(condition_id)


# Internal

@internal
@view
def _total_pool_value() -> uint256:
    return staticcall self.usdc.balanceOf(self.pool) + self.total_borrowed


@internal
@view
def _available_liquidity() -> uint256:
    return staticcall self.usdc.balanceOf(self.pool)


@internal
@view
def _current_rate() -> uint256:
    total: uint256 = self._total_pool_value()
    if total == 0:
        return self.base_rate_bps
    util: uint256 = (self.total_borrowed * PRECISION) // total
    if util <= self.kink_bps:
        return self.base_rate_bps + (self.slope1_bps * util) // self.kink_bps
    else:
        rate_at_kink: uint256 = self.base_rate_bps + self.slope1_bps
        excess: uint256 = util - self.kink_bps
        excess_range: uint256 = PRECISION - self.kink_bps
        return rate_at_kink + (self.slope2_bps * excess) // excess_range


@internal
@view
def _health_factor(loan_id: uint256, price: uint256) -> uint256:
    loan: Loan = self.loans[loan_id]
    if loan.repaid or loan.liquidated:
        return max_value(uint256)
    if loan.liquidation_price == 0:
        return max_value(uint256)
    return (price * PRECISION) // loan.liquidation_price


@internal
@view
def _is_eligible(condition_id: bytes32) -> bool:
    m: MarketParams = self.markets[condition_id]
    if not m.active:
        return False
    if m.token_id == 0:
        return False
    if (
        m.resolution_time > 0
        and block.timestamp + m.origination_cutoff > m.resolution_time
    ):
        return False
    return True


# Owner

@external
def set_rate_params(base: uint256, s1: uint256, s2: uint256, kink: uint256):
    ownable._check_owner()
    self.base_rate_bps = base
    self.slope1_bps = s1
    self.slope2_bps = s2
    self.kink_bps = kink


@external
def set_maintenance_margin(margin_bps: uint256):
    ownable._check_owner()
    assert margin_bps >= 500, "maintenance margin too low"
    assert margin_bps <= 10000, "maintenance margin too high"
    self.maintenance_margin_bps = margin_bps
