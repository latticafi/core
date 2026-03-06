# pragma version ~=0.4.3

from snekmate.auth import ownable

initializes: ownable

exports: (
    ownable.transfer_ownership,
    ownable.renounce_ownership,
    ownable.owner,
)

event PremiumCommitted:
    condition_id: bytes32
    borrower: address

event PremiumRevealed:
    condition_id: bytes32
    borrower: address
    premium: uint256

event PremiumCleared:
    condition_id: bytes32
    borrower: address

MAX_BPS: constant(uint256) = 10000

condition_id: public(bytes32)
authorized_pricer: public(address)
authorized_pool: public(address)
reveal_delay: public(uint256)
commitments: public(HashMap[address, bytes32])
premiums: public(HashMap[address, uint256])
commit_block: public(HashMap[address, uint256])
is_active: public(HashMap[address, bool])

@deploy
def __init__(condition_id: bytes32, authorized_pricer: address, reveal_delay: uint256):
    ownable.__init__()
    assert authorized_pricer != empty(address), "invalid pricer"
    self.condition_id = condition_id
    self.authorized_pricer = authorized_pricer
    self.reveal_delay = reveal_delay

@external
def set_authorized_pool(pool: address):
    ownable._check_owner()
    assert pool != empty(address), "invalid pool"
    self.authorized_pool = pool

@external
def commit(borrower: address, commitment: bytes32):
    assert msg.sender == self.authorized_pricer, "not authorized"
    assert self.commitments[borrower] == empty(bytes32), "already committed"
    assert commitment != empty(bytes32), "empty commitment"
    self.commitments[borrower] = commitment
    self.commit_block[borrower] = block.number
    log PremiumCommitted(condition_id=self.condition_id, borrower=borrower)

@external
def reveal(borrower: address, premium: uint256, salt: bytes32):
    assert msg.sender == self.authorized_pricer, "not authorized"
    assert self.commitments[borrower] != empty(bytes32), "not committed"
    assert not self.is_active[borrower], "already revealed"
    assert block.number >= self.commit_block[borrower] + self.reveal_delay, "reveal too early"
    assert premium <= MAX_BPS, "premium exceeds max"
    assert keccak256(abi_encode(premium, salt)) == self.commitments[borrower], "hash mismatch"
    self.premiums[borrower] = premium
    self.is_active[borrower] = True
    log PremiumRevealed(condition_id=self.condition_id, borrower=borrower, premium=premium)

@external
def clear_premium(borrower: address):
    assert msg.sender == self.authorized_pool, "not authorized"
    self.commitments[borrower] = empty(bytes32)
    self.premiums[borrower] = empty(uint256)
    self.commit_block[borrower] = empty(uint256)
    self.is_active[borrower] = False
    log PremiumCleared(condition_id=self.condition_id, borrower=borrower)

@external
@view
def get_premium(borrower: address) -> uint256:
    assert self.is_active[borrower], "premium not active"
    return self.premiums[borrower]
