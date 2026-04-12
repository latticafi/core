# pragma version ~=0.4.0

"""
@title Lattica Price Feed
@notice Pull-based oracle. Anyone submits a signed price attestation from
        the trusted oracle signer. The signer watches Polymarket CLOB
        off-chain and serves signed prices via HTTP. Zero gas for the oracle.
@dev    Uses snekmate ecdsa + eip712 for signature verification.
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step as ow
from snekmate.utils import ecdsa
from snekmate.utils import eip712_domain_separator as eip712

initializes: ownable
initializes: ow[ownable := ownable]
initializes: eip712

# EIP-712 Struct Typehash

PRICE_TYPEHASH: constant(bytes32) = keccak256(
    "PriceAttestation(bytes32 conditionId,uint256 price,uint256 timestamp,uint256 deadline)"
)

# Storage

struct PriceData:
    current_price: uint256
    previous_price: uint256
    current_timestamp: uint256
    previous_timestamp: uint256
    circuit_breaker_until: uint256


signer: public(address)
min_deviation: public(uint256)
circuit_breaker_threshold: public(uint256)
circuit_breaker_cooldown: public(uint256)

prices: public(HashMap[bytes32, PriceData])

# Events

event PriceUpdated:
    condition_id: indexed(bytes32)
    price: uint256
    timestamp: uint256


event CircuitBreakerTripped:
    condition_id: indexed(bytes32)
    old_price: uint256
    new_price: uint256


event SignerRotated:
    old_signer: address
    new_signer: address


# Constructor

@deploy
def __init__(
    _signer: address,
    admin: address,
    _min_deviation: uint256,
    _cb_threshold: uint256,
    _cb_cooldown: uint256,
):
    ownable.__init__()
    ow.__init__()
    ow._transfer_ownership(admin)
    eip712.__init__("LatticaPriceFeed", "1")
    self.signer = _signer
    self.min_deviation = _min_deviation
    self.circuit_breaker_threshold = _cb_threshold
    self.circuit_breaker_cooldown = _cb_cooldown


# Core

@external
def submit_price(
    condition_id: bytes32,
    price: uint256,
    timestamp: uint256,
    deadline: uint256,
    signature: Bytes[65],
):
    """
    @notice Permissionless — anyone can submit a signed price attestation.
            Oracle service signs off-chain, user/backend submits on-chain.
    """
    assert price <= 10**18, "invalid price"
    assert block.timestamp <= deadline, "attestation expired"

    pd: PriceData = self.prices[condition_id]
    assert block.timestamp >= pd.circuit_breaker_until, "circuit breaker active"
    assert timestamp > pd.current_timestamp, "not newer"
    assert timestamp <= block.timestamp, "future timestamp"

    # Verify signature
    struct_hash: bytes32 = keccak256(
        abi_encode(PRICE_TYPEHASH, condition_id, price, timestamp, deadline)
    )
    digest: bytes32 = eip712._hash_typed_data_v4(struct_hash)
    recovered: address = ecdsa._recover_sig(digest, signature)
    assert recovered != empty(address), "invalid signature"
    assert recovered == self.signer, "wrong signer"

    current: uint256 = pd.current_price

    # Deviation + circuit breaker (skip on first update)
    if current > 0:
        delta: uint256 = 0
        if price > current:
            delta = price - current
        else:
            delta = current - price

        assert delta >= self.min_deviation, "below min deviation"

        if delta > self.circuit_breaker_threshold:
            self.prices[condition_id].circuit_breaker_until = (
                block.timestamp + self.circuit_breaker_cooldown
            )
            log CircuitBreakerTripped(
                condition_id=condition_id, old_price=current, new_price=price
            )
            return
    self.prices[condition_id].previous_price = current
    self.prices[condition_id].previous_timestamp = pd.current_timestamp
    self.prices[condition_id].current_price = price
    self.prices[condition_id].current_timestamp = timestamp

    log PriceUpdated(
        condition_id=condition_id, price=price, timestamp=timestamp
    )


@external
@view
def get_price(condition_id: bytes32) -> (uint256, uint256):
    pd: PriceData = self.prices[condition_id]
    return (pd.current_price, pd.current_timestamp)


@external
@view
def is_circuit_broken(condition_id: bytes32) -> bool:
    return block.timestamp < self.prices[condition_id].circuit_breaker_until


# Admin

@external
def reset_circuit_breaker(condition_id: bytes32):
    ownable._check_owner()
    self.prices[condition_id].circuit_breaker_until = 0


@external
def set_signer(new_signer: address):
    ownable._check_owner()
    assert new_signer != empty(address), "zero address"
    old: address = self.signer
    self.signer = new_signer
    log SignerRotated(old_signer=old, new_signer=new_signer)


@external
def set_circuit_breaker_params(threshold: uint256, cooldown: uint256):
    ownable._check_owner()
    self.circuit_breaker_threshold = threshold
    self.circuit_breaker_cooldown = cooldown
