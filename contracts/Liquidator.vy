# pragma version ~=0.4.0

"""
@title Lattica Liquidator
@author Lattica Protocol
@license MIT
@notice Holds seized collateral. Liquidation operator sells on Polymarket CLOB,
        sends recovery USDC directly to LendingPool address,
        then calls settle() here to mark the liquidation resolved.
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow
from snekmate.tokens.interfaces import IERC1155
from snekmate.tokens.interfaces import IERC1155Receiver

initializes: ownable
initializes: ow[ownable := ownable]
implements: IERC1155Receiver

# Data Structures

struct PendingLiquidation:
    token_id: uint256
    collateral_amount: uint256
    condition_id: bytes32
    principal: uint256
    epoch_end: uint256
    seized_at: uint256
    settled: bool


# Storage

pool: public(address)
operator: public(address)
ctf_token: public(address)

pending: public(HashMap[uint256, PendingLiquidation])
pending_count: public(uint256)
total_seized_principal: public(uint256)
total_recovered: public(uint256)

# Events

event CollateralSeized:
    loan_id: indexed(uint256)
    token_id: uint256
    collateral_amount: uint256
    principal: uint256


event LiquidationSettled:
    loan_id: indexed(uint256)
    recovered: uint256


event EmergencyClaimed:
    loan_id: indexed(uint256)


# Constructor

@deploy
def __init__(
    pool_addr: address,
    operator_addr: address,
    ctf_token_addr: address,
    admin: address,
):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(admin)
    self.pool = pool_addr
    self.operator = operator_addr
    self.ctf_token = ctf_token_addr


# Called by LendingPool after marking loan liquidated

@external
def seize(
    loan_id: uint256,
    token_id: uint256,
    collateral_amount: uint256,
    condition_id: bytes32,
    principal: uint256,
    epoch_end: uint256,
):
    assert msg.sender == self.pool, "not pool"

    self.pending[loan_id] = PendingLiquidation(
        token_id=token_id,
        collateral_amount=collateral_amount,
        condition_id=condition_id,
        principal=principal,
        epoch_end=epoch_end,
        seized_at=block.timestamp,
        settled=False,
    )
    self.pending_count += 1
    self.total_seized_principal += principal

    log CollateralSeized(
        loan_id=loan_id,
        token_id=token_id,
        collateral_amount=collateral_amount,
        principal=principal,
    )


# Called by liquidation operator after selling collateral on CLOB and sending
# recovery USDC directly to pool address.

@external
def settle(loan_id: uint256, recovered: uint256):
    assert msg.sender == self.operator, "not operator"
    p: PendingLiquidation = self.pending[loan_id]
    assert p.seized_at > 0, "no pending liquidation"
    assert not p.settled, "already settled"

    self.pending[loan_id].settled = True
    self.pending_count -= 1
    self.total_recovered += recovered

    log LiquidationSettled(loan_id=loan_id, recovered=recovered)


# Emergency: admin claims stuck collateral

@external
def emergency_claim(loan_id: uint256):
    ownable._check_owner()
    p: PendingLiquidation = self.pending[loan_id]
    assert p.seized_at > 0, "no pending liquidation"
    assert not p.settled, "already settled"

    extcall IERC1155(self.ctf_token).safeTransferFrom(
        self, ownable.owner, p.token_id, p.collateral_amount, b""
    )

    self.pending[loan_id].settled = True
    self.pending_count -= 1
    log EmergencyClaimed(loan_id=loan_id)


# Admin

@external
def set_operator(new_operator: address):
    ownable._check_owner()
    assert new_operator != empty(address), "zero address"
    self.operator = new_operator


# ERC1155 receiver (snekmate-compatible signatures)

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
