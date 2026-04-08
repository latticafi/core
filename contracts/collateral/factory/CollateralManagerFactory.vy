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


event CMDeployed:
    condition_id: bytes32
    cm: address


event ImplementationUpdated:
    implementation: address


implementation: public(address)
cm_count: public(uint256)
cm_list: public(DynArray[address, 4096])
cm_by_market: public(HashMap[bytes32, address])


@deploy
def __init__(_implementation: address):
    assert _implementation != empty(address), "empty implementation"
    ownable.__init__()
    ownable_2step.__init__()
    self.implementation = _implementation


@external
def deploy_cm(
    condition_id: bytes32,
    ctf_address: address,
    price_feed: address,
    market_registry: address,
) -> address:
    ownable._check_owner()
    assert self.cm_by_market[condition_id] == empty(address), "cm exists"

    cm: address = create_from_blueprint(
        self.implementation,
        condition_id,
        ctf_address,
        price_feed,
        market_registry,
        code_offset=3,
    )

    self.cm_list.append(cm)
    self.cm_by_market[condition_id] = cm
    self.cm_count += 1

    log CMDeployed(condition_id=condition_id, cm=cm)
    return cm


@external
def set_implementation(new_impl: address):
    ownable._check_owner()
    assert new_impl != empty(address), "empty implementation"
    self.implementation = new_impl
    log ImplementationUpdated(implementation=new_impl)


@view
@external
def get_cm(condition_id: bytes32) -> address:
    return self.cm_by_market[condition_id]
