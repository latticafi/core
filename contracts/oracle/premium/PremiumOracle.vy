# pragma version ~=0.4.3

from snekmate.auth import ownable

initializes: ownable

exports: (
    ownable.transfer_ownership,
    ownable.renounce_ownership,
    ownable.owner,
)


event QuoteConsumed:
    condition_id: bytes32
    borrower: address
    premium_bps: uint256
    amount: uint256


event PricerUpdated:
    new_pricer: address


MAX_BPS: constant(uint256) = 10000

DOMAIN_TYPEHASH: constant(bytes32) = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)
QUOTE_TYPEHASH: constant(bytes32) = keccak256(
    "PremiumQuote(address borrower,bytes32 conditionId,uint256 premiumBps,uint256 amount,uint256 deadline,uint256 nonce)"
)
NAME_HASH: constant(bytes32) = keccak256("LatticaPremiumOracle")
VERSION_HASH: constant(bytes32) = keccak256("1")

condition_id: public(bytes32)
authorized_pricer: public(address)
authorized_pool: public(address)
nonces: public(HashMap[address, uint256])
DOMAIN_SEPARATOR: public(bytes32)


@deploy
def __init__(_condition_id: bytes32, _authorized_pricer: address):
    ownable.__init__()
    assert _authorized_pricer != empty(address), "invalid pricer"
    self.condition_id = _condition_id
    self.authorized_pricer = _authorized_pricer
    self.DOMAIN_SEPARATOR = keccak256(
        abi_encode(
            DOMAIN_TYPEHASH,
            NAME_HASH,
            VERSION_HASH,
            chain.id,
            self,
        )
    )


@external
def verify_and_consume(
    borrower: address,
    premium_bps: uint256,
    amount: uint256,
    deadline: uint256,
    signature: Bytes[65],
) -> uint256:
    assert msg.sender == self.authorized_pool, "not authorized"
    assert block.timestamp <= deadline, "quote expired"
    assert premium_bps <= MAX_BPS, "premium exceeds max"

    nonce: uint256 = self.nonces[borrower]
    struct_hash: bytes32 = keccak256(
        abi_encode(
            QUOTE_TYPEHASH,
            borrower,
            self.condition_id,
            premium_bps,
            amount,
            deadline,
            nonce,
        )
    )
    digest: bytes32 = keccak256(
        concat(b"\x19\x01", self.DOMAIN_SEPARATOR, struct_hash)
    )

    assert len(signature) == 65, "invalid sig length"
    r: uint256 = extract32(signature, 0, output_type=uint256)
    s: uint256 = extract32(signature, 32, output_type=uint256)
    v: uint256 = convert(slice(signature, 64, 1), uint256)
    if v < 27:
        v += 27

    signer: address = ecrecover(digest, v, r, s)
    assert signer == self.authorized_pricer, "invalid signer"

    self.nonces[borrower] = nonce + 1

    log QuoteConsumed(
        condition_id=self.condition_id,
        borrower=borrower,
        premium_bps=premium_bps,
        amount=amount,
    )
    return premium_bps


@external
def set_authorized_pool(pool: address):
    ownable._check_owner()
    assert pool != empty(address), "invalid pool"
    self.authorized_pool = pool


@external
def set_authorized_pricer(new_pricer: address):
    ownable._check_owner()
    assert new_pricer != empty(address), "invalid pricer"
    self.authorized_pricer = new_pricer
    log PricerUpdated(new_pricer=new_pricer)


@view
@external
def get_nonce(borrower: address) -> uint256:
    return self.nonces[borrower]
