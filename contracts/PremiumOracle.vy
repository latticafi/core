# pragma version ~=0.4.0

"""
@title Lattica Premium Oracle
@notice Verifies WARHORSE-signed EIP-712 premium quotes on-chain.
@dev    Uses snekmate ecdsa for signature recovery (malleability-safe)
        and eip712_domain_separator for domain separator management.
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow
from snekmate.utils import ecdsa
from snekmate.utils import eip712_domain_separator as eip712

initializes: ownable
initializes: ow[ownable := ownable]
initializes: eip712

# EIP-712 Struct Typehash

QUOTE_TYPEHASH: constant(bytes32) = keccak256(
    "PremiumQuote(address borrower,bytes32 conditionId,uint256 premiumBps,uint256 amount,uint256 deadline,uint256 nonce)"
)

# Storage

pool: public(immutable(address))
pricer: public(address)
nonces: public(HashMap[address, uint256])
paused: public(bool)

# Events

event QuoteConsumed:
    borrower: indexed(address)
    nonce: uint256
    premium_bps: uint256


event PricerRotated:
    old_pricer: address
    new_pricer: address


# Constructor

@deploy
def __init__(pricer_addr: address, pool_addr: address, admin: address):
    ow.__init__()
    ow._transfer_ownership(admin)
    eip712.__init__("LatticaPremiumOracle", "1")

    self.pricer = pricer_addr
    pool = pool_addr


# Core: Verify and consume a signed quote

@external
def verify_quote(
    borrower: address,
    condition_id: bytes32,
    premium_bps: uint256,
    amount: uint256,
    deadline: uint256,
    nonce: uint256,
    signature: Bytes[65],
) -> bool:
    assert msg.sender == pool, "not pool"
    assert not self.paused, "paused"
    assert block.timestamp <= deadline, "quote expired"
    assert nonce == self.nonces[borrower], "invalid nonce"

    struct_hash: bytes32 = keccak256(
        abi_encode(
            QUOTE_TYPEHASH,
            borrower,
            condition_id,
            premium_bps,
            amount,
            deadline,
            nonce,
        )
    )

    # snekmate eip712: combines domain separator + struct hash + \x19\x01 prefix
    digest: bytes32 = eip712._hash_typed_data_v4(struct_hash)

    # snekmate ecdsa: recovers with malleability protection built in
    recovered: address = ecdsa._recover_sig(digest, signature)
    assert recovered != empty(address), "invalid signature"
    assert recovered == self.pricer, "wrong signer"

    self.nonces[borrower] = nonce + 1
    log QuoteConsumed(borrower, nonce, premium_bps)
    return True


# Views

@external
@view
def get_nonce(borrower: address) -> uint256:
    return self.nonces[borrower]


# Admin

@external
def set_paused(_paused: bool):
    assert msg.sender == ow.owner, "not owner"
    self.paused = _paused


@external
def set_pricer(new_pricer: address):
    assert msg.sender == ow.owner, "not owner"
    assert new_pricer != empty(address), "zero address"
    old: address = self.pricer
    self.pricer = new_pricer
    log PricerRotated(old, new_pricer)
