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


event LiquidatorDeployed:
    condition_id: bytes32
    liquidator: address


event ImplementationUpdated:
    implementation: address


implementation: public(address)
liq_count: public(uint256)
liq_list: public(DynArray[address, 4096])
liq_by_market: public(HashMap[bytes32, address])


@deploy
def __init__(_implementation: address):
    assert _implementation != empty(address), "empty implementation"
    ownable.__init__()
    ownable_2step.__init__()
    self.implementation = _implementation


@external
def deploy_liquidator(
    condition_id: bytes32,
    lending_pool: address,
    collateral_manager: address,
    price_feed: address,
    usdc_e: address,
    ctf: address,
    liquidation_fee_bps: uint256,
) -> address:
    ownable._check_owner()
    assert self.liq_by_market[condition_id] == empty(
        address
    ), "liquidator exists"

    liq: address = create_from_blueprint(
        self.implementation,
        condition_id,
        lending_pool,
        collateral_manager,
        price_feed,
        usdc_e,
        ctf,
        liquidation_fee_bps,
        code_offset=3,
    )

    self.liq_list.append(liq)
    self.liq_by_market[condition_id] = liq
    self.liq_count += 1

    log LiquidatorDeployed(condition_id=condition_id, liquidator=liq)
    return liq


@external
def set_implementation(new_impl: address):
    ownable._check_owner()
    assert new_impl != empty(address), "empty implementation"
    self.implementation = new_impl
    log ImplementationUpdated(implementation=new_impl)


@view
@external
def get_liquidator(condition_id: bytes32) -> address:
    return self.liq_by_market[condition_id]
