# pragma version ~=0.4.0

"""
@title Lattica Lending Pool
@author Lattica Protocol
@license MIT
@notice User-facing entry point. Holds USDC and ERC1155 collateral.
        Handles all token movements and Reserve interactions.
        Delegates state and computation to PoolCore.
"""

from ethereum.ercs import IERC20
from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow
from snekmate.utils import pausable as ps
from snekmate.tokens.interfaces import IERC1155
from snekmate.tokens.interfaces import IERC1155Receiver

initializes: ownable
initializes: ow[ownable := ownable]
initializes: ps

exports: ow.owner
exports: ps.paused

implements: IERC1155Receiver

from interfaces import IPoolCore as IPoolCore
from interfaces import ILiquidator as ILiquidator
from interfaces import IPriceFeed as IPriceFeed
from interfaces import IReserve as IReserve


# Constants

PRECISION: constant(uint256) = 10_000
MAX_PRICE_AGE: constant(uint256) = 3600

# Storage

usdc: public(IERC20)
ctf_token: public(address)
core: public(address)
liquidator: public(address)
reserve: public(address)
price_feed: public(address)
guardian: public(address)
initialized: public(bool)

# Events

event Deposited:
    lender: indexed(address)
    amount: uint256
    shares: uint256


event Withdrawn:
    lender: indexed(address)
    shares: uint256
    amount: uint256


event LoanOriginated:
    loan_id: indexed(uint256)
    borrower: indexed(address)
    condition_id: indexed(bytes32)
    principal: uint256
    premium: uint256
    epoch_end: uint256


event PremiumCollected:
    loan_id: indexed(uint256)
    premium: uint256
    retention: uint256


event LoanRepaid:
    loan_id: indexed(uint256)


event LoanRolled:
    old_loan_id: indexed(uint256)
    new_loan_id: indexed(uint256)


event LoanLiquidated:
    loan_id: indexed(uint256)


# Constructor + Init

@deploy
def __init__(usdc_addr: address, ctf_token_addr: address, admin: address):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(admin)
    ps.__init__()
    self.usdc = IERC20(usdc_addr)
    self.ctf_token = ctf_token_addr


@external
def initialize(
    core_addr: address,
    liquidator_addr: address,
    reserve_addr: address,
    price_feed_addr: address,
    guardian_addr: address,
):
    assert not self.initialized, "already initialized"
    ownable._check_owner()
    assert core_addr != empty(address), "zero core"
    assert liquidator_addr != empty(address), "zero liquidator"
    assert reserve_addr != empty(address), "zero reserve"
    assert price_feed_addr != empty(address), "zero price feed"

    self.core = core_addr
    self.liquidator = liquidator_addr
    self.reserve = reserve_addr
    self.price_feed = price_feed_addr
    self.guardian = guardian_addr
    self.initialized = True


@internal
def _check():
    assert self.initialized, "not initialized"
    ps._require_not_paused()


# Lender

@external
def deposit(amount: uint256) -> uint256:
    self._check()
    extcall self.usdc.transferFrom(msg.sender, self, amount)
    shares: uint256 = extcall IPoolCore(self.core).deposit_shares(
        msg.sender, amount
    )
    log Deposited(lender=msg.sender, amount=amount, shares=shares)
    return shares


@external
def withdraw(shares: uint256) -> uint256:
    self._check()
    amount: uint256 = extcall IPoolCore(self.core).withdraw_shares(
        msg.sender, shares
    )
    extcall self.usdc.transfer(msg.sender, amount)
    log Withdrawn(lender=msg.sender, shares=shares, amount=amount)
    return amount


# Borrower

@external
def borrow(
    condition_id: bytes32,
    collateral_amount: uint256,
    borrow_amount: uint256,
    epoch_length: uint256,
    premium_bps: uint256,
    deadline: uint256,
    nonce: uint256,
    signature: Bytes[65],
) -> uint256:
    self._check()

    loan_id: uint256 = extcall IPoolCore(self.core).originate(
        msg.sender,
        condition_id,
        collateral_amount,
        borrow_amount,
        epoch_length,
        premium_bps,
        deadline,
        nonce,
        signature,
    )

    loan: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(loan_id)

    extcall IERC1155(self.ctf_token).safeTransferFrom(
        msg.sender, self, loan.token_id, collateral_amount, b""
    )

    net_disburse: uint256 = (
        borrow_amount - loan.premium_paid - loan.interest_due
    )
    extcall self.usdc.transfer(msg.sender, net_disburse)

    retention: uint256 = self._route_to_reserve(loan.premium_paid)

    log LoanOriginated(
        loan_id=loan_id,
        borrower=msg.sender,
        condition_id=condition_id,
        principal=borrow_amount,
        premium=loan.premium_paid,
        epoch_end=loan.epoch_end,
    )
    log PremiumCollected(
        loan_id=loan_id, premium=loan.premium_paid, retention=retention
    )
    return loan_id


@external
def repay(loan_id: uint256):
    self._check()
    loan: IPoolCore.Loan = extcall IPoolCore(self.core).settle_repay(
        loan_id, msg.sender
    )

    extcall self.usdc.transferFrom(msg.sender, self, loan.principal)
    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, msg.sender, loan.token_id, loan.collateral_amount, b""
    )

    log LoanRepaid(loan_id=loan_id)


@external
def roll_loan(
    old_loan_id: uint256,
    epoch_length: uint256,
    premium_bps: uint256,
    deadline: uint256,
    nonce: uint256,
    signature: Bytes[65],
) -> uint256:
    self._check()

    new_loan_id: uint256 = 0
    total_cost: uint256 = 0
    old_loan: IPoolCore.Loan = empty(IPoolCore.Loan)
    new_loan_id, total_cost, old_loan = extcall IPoolCore(
        self.core
    ).settle_roll(
        old_loan_id,
        msg.sender,
        epoch_length,
        premium_bps,
        deadline,
        nonce,
        signature,
    )

    extcall self.usdc.transferFrom(msg.sender, self, total_cost)

    new_loan: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(
        new_loan_id
    )
    retention: uint256 = self._route_to_reserve(new_loan.premium_paid)

    log LoanRolled(old_loan_id=old_loan_id, new_loan_id=new_loan_id)
    log LoanOriginated(
        loan_id=new_loan_id,
        borrower=msg.sender,
        condition_id=old_loan.condition_id,
        principal=old_loan.principal,
        premium=new_loan.premium_paid,
        epoch_end=new_loan.epoch_end,
    )
    log PremiumCollected(
        loan_id=new_loan_id, premium=new_loan.premium_paid, retention=retention
    )
    return new_loan_id


# Liquidation

@external
def trigger_liquidation(loan_id: uint256):
    assert self.initialized, "not initialized"

    loan_pre: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(loan_id)
    assert loan_pre.borrower != empty(address), "loan does not exist"
    assert block.timestamp <= loan_pre.epoch_end, "use claim_expired"

    price: uint256 = 0
    ts: uint256 = 0
    price, ts = staticcall IPriceFeed(self.price_feed).get_price(
        loan_pre.condition_id
    )
    assert ts > 0 and block.timestamp - ts <= MAX_PRICE_AGE, "stale price"

    hf: uint256 = staticcall IPoolCore(self.core).health_factor(loan_id)
    assert hf < PRECISION, "position is healthy"

    loan: IPoolCore.Loan = extcall IPoolCore(self.core).mark_liquidated(loan_id)
    extcall IReserve(self.reserve).cover_loss(loan.principal)

    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, self.liquidator, loan.token_id, loan.collateral_amount, b""
    )
    extcall ILiquidator(self.liquidator).seize(
        loan_id,
        loan.token_id,
        loan.collateral_amount,
        loan.condition_id,
        loan.principal,
        loan.epoch_end,
    )

    log LoanLiquidated(loan_id=loan_id)


@external
def claim_expired(loan_id: uint256):
    assert self.initialized, "not initialized"

    loan_pre: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(loan_id)
    assert loan_pre.borrower != empty(address), "loan does not exist"
    assert block.timestamp > loan_pre.epoch_end, "epoch not expired"

    loan: IPoolCore.Loan = extcall IPoolCore(self.core).mark_liquidated(loan_id)
    extcall IReserve(self.reserve).cover_loss(loan.principal)

    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, self.liquidator, loan.token_id, loan.collateral_amount, b""
    )
    extcall ILiquidator(self.liquidator).seize(
        loan_id,
        loan.token_id,
        loan.collateral_amount,
        loan.condition_id,
        loan.principal,
        loan.epoch_end,
    )

    log LoanLiquidated(loan_id=loan_id)


# Reserve routing

@internal
def _route_to_reserve(premium: uint256) -> uint256:
    retention_bps: uint256 = staticcall IReserve(
        self.reserve
    ).current_retention_bps()
    retention: uint256 = (premium * retention_bps) // PRECISION
    if retention > 0:
        extcall self.usdc.transfer(self.reserve, retention)
        extcall IReserve(self.reserve).deposit(retention)
    return retention


# Admin

@external
def pause():
    assert (
        msg.sender == self.guardian or msg.sender == ownable.owner
    ), "not guardian"
    ps._pause()


@external
def unpause():
    ownable._check_owner()
    ps._unpause()


@external
def set_guardian(_guardian: address):
    ownable._check_owner()
    self.guardian = _guardian


# ERC1155 receiver

@external
def onERC1155Received(
    _operator: address,
    _from: address,
    _id: uint256,
    _value: uint256,
    _data: Bytes[1_024],
) -> bytes4:
    return method_id(
        "onERC1155Received(address,address,uint256,uint256,bytes)",
        output_type=bytes4,
    )


@external
def onERC1155BatchReceived(
    _operator: address,
    _from: address,
    _ids: DynArray[uint256, 65_535],
    _values: DynArray[uint256, 65_535],
    _data: Bytes[1_024],
) -> bytes4:
    return method_id(
        "onERC1155BatchReceived(address,address,uint256[],uint256[],bytes)",
        output_type=bytes4,
    )


@external
@view
def supportsInterface(interfaceId: bytes4) -> bool:
    return interfaceId == 0x4e2312e0 or interfaceId == 0x01ffc9a7
