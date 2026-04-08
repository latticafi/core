# pragma version ~=0.4.3

from snekmate.auth import ownable_2step
from snekmate.auth import ownable

initializes: ownable
initializes: ownable_2step[ownable := ownable]

exports: (
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
    ownable_2step.renounce_ownership,
    ownable.owner,
    ownable_2step.pending_owner,
)


event AddressSet:
    id: uint256
    addr: address


addresses: HashMap[uint256, address]
num_entries: uint256


@deploy
def __init__():
    ownable.__init__()
    ownable_2step.__init__()


@view
@external
def get_address(id: uint256) -> address:
    addr: address = self.addresses[id]
    assert addr != empty(address), "address not set"
    return addr


@external
def set_address(id: uint256, addr: address):
    ownable._check_owner()
    self.addresses[id] = addr
    if id >= self.num_entries:
        self.num_entries = id + 1
    log AddressSet(id=id, addr=addr)


@view
@external
def max_id() -> uint256:
    return self.num_entries
