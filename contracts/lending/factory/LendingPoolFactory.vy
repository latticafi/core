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

event PoolDeployed:
    condition_id: bytes32
    pool: address

event ImplementationUpdated:
    implementation: address

implementation: public(address)
pool_count: public(uint256)
pool_list: public(DynArray[address, 4096])
pool_by_market: public(HashMap[bytes32, address])


@deploy
def __init__(_implementation: address):
    assert _implementation != empty(address), "empty implementation"
    ownable.__init__()
    ownable_2step.__init__()
    self.implementation = _implementation


@external
def deploy_pool(
    condition_id: bytes32,
    usdc_e: address,
    collateral_manager: address,
    premium_oracle: address,
    interest_rate_model: address,
    market_registry: address,
    price_feed: address,
    min_loan_duration: uint256,
    max_loan_duration: uint256,
) -> address:
    ownable._check_owner()
    assert self.pool_by_market[condition_id] == empty(address), "pool exists"

    pool: address = create_from_blueprint(
        self.implementation,
        condition_id,
        usdc_e,
        collateral_manager,
        premium_oracle,
        interest_rate_model,
        market_registry,
        price_feed,
        min_loan_duration,
        max_loan_duration,
        code_offset=3,
    )

    self.pool_list.append(pool)
    self.pool_by_market[condition_id] = pool
    self.pool_count += 1

    log PoolDeployed(condition_id=condition_id, pool=pool)
    return pool


@external
def set_implementation(new_impl: address):
    ownable._check_owner()
    assert new_impl != empty(address), "empty implementation"
    self.implementation = new_impl
    log ImplementationUpdated(implementation=new_impl)


@view
@external
def get_pool(condition_id: bytes32) -> address:
    return self.pool_by_market[condition_id]
