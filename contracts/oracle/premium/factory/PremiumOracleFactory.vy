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

event OracleDeployed:
    condition_id: bytes32
    oracle: address

event ImplementationUpdated:
    implementation: address

implementation: public(address)
oracle_count: public(uint256)
oracle_list: public(DynArray[address, 4096])
oracle_by_market: public(HashMap[bytes32, address])

@deploy
def __init__(_implementation: address):
    ownable.__init__()
    ownable_2step.__init__()
    assert _implementation != empty(address), "invalid implementation"
    self.implementation = _implementation

@external
def deploy_oracle(condition_id: bytes32, authorized_pricer: address, reveal_delay: uint256) -> address:
    ownable._check_owner()
    assert self.oracle_by_market[condition_id] == empty(address), "oracle already exists"
    oracle: address = create_from_blueprint(self.implementation, condition_id, authorized_pricer, reveal_delay, code_offset=3)
    self.oracle_by_market[condition_id] = oracle
    self.oracle_list.append(oracle)
    self.oracle_count += 1
    log OracleDeployed(condition_id=condition_id, oracle=oracle)
    return oracle

@external
def set_implementation(new_impl: address):
    ownable._check_owner()
    assert new_impl != empty(address), "invalid implementation"
    self.implementation = new_impl
    log ImplementationUpdated(implementation=new_impl)

@external
@view
def get_oracle(condition_id: bytes32) -> address:
    return self.oracle_by_market[condition_id]
