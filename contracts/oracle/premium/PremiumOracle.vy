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
    epoch: uint256

event PremiumRevealed:
    condition_id: bytes32
    epoch: uint256
    premium: uint256

MAX_BPS: constant(uint256) = 10000

condition_id: public(bytes32)
authorized_pricer: public(address)
reveal_delay: public(uint256)
commitments: public(HashMap[uint256, bytes32])
premiums: public(HashMap[uint256, uint256])
commit_block: public(HashMap[uint256, uint256])
is_active: public(HashMap[uint256, bool])

@deploy
def __init__(condition_id: bytes32, authorized_pricer: address, reveal_delay: uint256):
    ownable.__init__()
    assert authorized_pricer != empty(address), "invalid pricer"
    self.condition_id = condition_id
    self.authorized_pricer = authorized_pricer
    self.reveal_delay = reveal_delay

@external
def commit(epoch: uint256, commitment: bytes32):
    assert msg.sender == self.authorized_pricer, "not authorized"
    assert self.commitments[epoch] == empty(bytes32), "already committed"
    assert commitment != empty(bytes32), "empty commitment"
    self.commitments[epoch] = commitment
    self.commit_block[epoch] = block.number
    log PremiumCommitted(condition_id=self.condition_id, epoch=epoch)

@external
def reveal(epoch: uint256, premium: uint256, salt: bytes32):
    assert msg.sender == self.authorized_pricer, "not authorized"
    assert self.commitments[epoch] != empty(bytes32), "not committed"
    assert not self.is_active[epoch], "already revealed"
    assert block.number >= self.commit_block[epoch] + self.reveal_delay, "reveal too early"
    assert premium <= MAX_BPS, "premium exceeds max"
    assert keccak256(abi_encode(premium, salt)) == self.commitments[epoch], "hash mismatch"
    self.premiums[epoch] = premium
    self.is_active[epoch] = True
    log PremiumRevealed(condition_id=self.condition_id, epoch=epoch, premium=premium)

@external
@view
def get_premium(epoch: uint256) -> uint256:
    assert self.is_active[epoch], "premium not active"
    return self.premiums[epoch]
