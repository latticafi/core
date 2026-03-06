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

event FeedDeployed:
    condition_id: bytes32
    feed: address

event ImplementationUpdated:
    implementation: address

implementation: public(address)
feed_count: public(uint256)
feed_list: public(DynArray[address, 4096])
feed_by_market: public(HashMap[bytes32, address])

@deploy
def __init__(_implementation: address):
    assert _implementation != empty(address), "empty implementation"
    ownable.__init__()
    ownable_2step.__init__()
    self.implementation = _implementation

@external
def deploy_feed(
    condition_id: bytes32,
    authorized_updater: address,
    deviation_threshold_bps: uint256,
    staleness_limit: uint256,
    circuit_breaker_threshold_bps: uint256,
    circuit_breaker_cooldown: uint256,
) -> address:
    ownable._check_owner()
    assert self.feed_by_market[condition_id] == empty(address), "feed exists"

    feed: address = create_from_blueprint(
        self.implementation,
        condition_id,
        authorized_updater,
        deviation_threshold_bps,
        staleness_limit,
        circuit_breaker_threshold_bps,
        circuit_breaker_cooldown,
        code_offset=3,
    )

    self.feed_list.append(feed)
    self.feed_by_market[condition_id] = feed
    self.feed_count += 1

    log FeedDeployed(condition_id=condition_id, feed=feed)
    return feed

@external
def set_implementation(new_impl: address):
    ownable._check_owner()
    assert new_impl != empty(address), "empty implementation"
    self.implementation = new_impl
    log ImplementationUpdated(implementation=new_impl)

@view
@external
def get_feed(condition_id: bytes32) -> address:
    return self.feed_by_market[condition_id]
