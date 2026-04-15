# pragma version ~=0.4.0

"""
@title Lattica Lending Pool
@author Lattica Protocol
@license MIT
"""

from ethereum.ercs import IERC20
from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow
from snekmate.utils import pausable as ps
from snekmate.utils import ecdsa
from snekmate.utils import eip712_domain_separator as eip712
from snekmate.tokens.interfaces import IERC1155
from snekmate.tokens.interfaces import IERC1155Receiver

initializes: ownable
initializes: ow[ownable := ownable]
initializes: ps
initializes: eip712

exports: ow.owner
exports: ps.paused

implements: IERC1155Receiver

from interfaces import IPoolCore as IPoolCore
from interfaces import IReserve as IReserve

# Constants

PRECISION: constant(uint256) = 10_000

PRICE_TYPEHASH: constant(bytes32) = keccak256(
    "PriceAttestation(bytes32 conditionId,uint256 price,uint256 timestamp,uint256 deadline)"
)

# Storage

usdc: public(IERC20)
ctf_token: public(address)
core: public(address)
reserve: public(address)
oracle_signer: public(address)
operator: public(address)
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
    collateral_to: indexed(address)
    token_id: uint256
    collateral_amount: uint256
    principal: uint256


# Constructor + Init

@deploy
def __init__(usdc_addr: address, ctf_token_addr: address, owner: address):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(owner)
    ps.__init__()
    eip712.__init__("LatticaPriceFeed", "1")
    self.usdc = IERC20(usdc_addr)
    self.ctf_token = ctf_token_addr


@external
def initialize(
    core_addr: address,
    reserve_addr: address,
    _oracle_signer: address,
    operator_addr: address,
):
    assert not self.initialized, "already initialized"
    ownable._check_owner()
    assert core_addr != empty(address), "zero core"
    assert reserve_addr != empty(address), "zero reserve"
    assert _oracle_signer != empty(address), "zero signer"

    self.core = core_addr
    self.reserve = reserve_addr
    self.oracle_signer = _oracle_signer
    self.operator = operator_addr
    self.initialized = True


@internal
def _check():
    assert self.initialized, "not initialized"
    ps._require_not_paused()


@internal
@view
def _verify_price(
    condition_id: bytes32,
    price: uint256,
    timestamp: uint256,
    deadline: uint256,
    signature: Bytes[65],
) -> uint256:
    assert price > 0 and price <= 10**18, "invalid price"
    assert block.timestamp <= deadline, "attestation expired"
    assert timestamp <= block.timestamp, "future timestamp"

    struct_hash: bytes32 = keccak256(
        abi_encode(PRICE_TYPEHASH, condition_id, price, timestamp, deadline)
    )
    digest: bytes32 = eip712._hash_typed_data_v4(struct_hash)
    recovered: address = ecdsa._recover_sig(digest, signature)
    assert recovered != empty(address), "invalid signature"
    assert recovered == self.oracle_signer, "wrong signer"

    return price


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
    price: uint256,
    price_timestamp: uint256,
    price_deadline: uint256,
    price_signature: Bytes[65],
) -> uint256:
    self._check()

    verified_price: uint256 = self._verify_price(
        condition_id, price, price_timestamp, price_deadline, price_signature
    )

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
        verified_price,
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
    price: uint256,
    price_timestamp: uint256,
    price_deadline: uint256,
    price_signature: Bytes[65],
) -> uint256:
    self._check()

    old_loan_pre: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(
        old_loan_id
    )
    verified_price: uint256 = self._verify_price(
        old_loan_pre.condition_id,
        price,
        price_timestamp,
        price_deadline,
        price_signature,
    )

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
        verified_price,
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


# Liquidation — restricted to operator/owner (backend)

@external
# No pause check — liquidations must work even when pool is paused
def trigger_liquidation(
    loan_id: uint256,
    price: uint256,
    price_timestamp: uint256,
    price_deadline: uint256,
    price_signature: Bytes[65],
):
    assert self.initialized, "not initialized"
    assert (
        msg.sender == self.operator or msg.sender == ownable.owner
    ), "not authorized"

    loan_pre: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(loan_id)
    assert loan_pre.borrower != empty(address), "loan does not exist"
    assert block.timestamp <= loan_pre.epoch_end, "use claim_expired"

    verified_price: uint256 = self._verify_price(
        loan_pre.condition_id,
        price,
        price_timestamp,
        price_deadline,
        price_signature,
    )

    hf: uint256 = staticcall IPoolCore(self.core).health_factor(
        loan_id, verified_price
    )
    assert hf < PRECISION, "position is healthy"

    loan: IPoolCore.Loan = extcall IPoolCore(self.core).mark_liquidated(loan_id)
    extcall IReserve(self.reserve).cover_loss(loan.principal)

    # Transfer collateral directly to caller (backend sells on CLOB)
    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, msg.sender, loan.token_id, loan.collateral_amount, b""
    )

    log LoanLiquidated(
        loan_id=loan_id,
        collateral_to=msg.sender,
        token_id=loan.token_id,
        collateral_amount=loan.collateral_amount,
        principal=loan.principal,
    )


@external
# No pause check — expiry claims must work even when pool is paused
def claim_expired(loan_id: uint256):
    assert self.initialized, "not initialized"
    assert (
        msg.sender == self.operator or msg.sender == ownable.owner
    ), "not authorized"

    loan_pre: IPoolCore.Loan = staticcall IPoolCore(self.core).get_loan(loan_id)
    assert loan_pre.borrower != empty(address), "loan does not exist"
    assert block.timestamp > loan_pre.epoch_end, "epoch not expired"

    loan: IPoolCore.Loan = extcall IPoolCore(self.core).mark_liquidated(loan_id)
    extcall IReserve(self.reserve).cover_loss(loan.principal)

    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, msg.sender, loan.token_id, loan.collateral_amount, b""
    )

    log LoanLiquidated(
        loan_id=loan_id,
        collateral_to=msg.sender,
        token_id=loan.token_id,
        collateral_amount=loan.collateral_amount,
        principal=loan.principal,
    )


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


# Owner

@external
def pause():
    assert (
        msg.sender == self.operator or msg.sender == ownable.owner
    ), "not authorized"
    ps._pause()


@external
def unpause():
    ownable._check_owner()
    ps._unpause()


@external
def set_operator(_operator: address):
    ownable._check_owner()
    self.operator = _operator


@external
def set_oracle_signer(_signer: address):
    ownable._check_owner()
    assert _signer != empty(address), "zero address"
    self.oracle_signer = _signer


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
