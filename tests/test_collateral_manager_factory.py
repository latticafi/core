import boa


def test_initial_state(collateral_manager_factory, collateral_manager_blueprint, deployer):
    assert collateral_manager_factory.implementation() == collateral_manager_blueprint.address
    assert collateral_manager_factory.cm_count() == 0
    assert collateral_manager_factory.owner() == deployer


def test_deploy_cm(collateral_manager_factory, deployer, condition_id, mock_ctf, price_feed, market_registry):
    with boa.env.prank(deployer):
        cm_addr = collateral_manager_factory.deploy_cm(
            condition_id, mock_ctf.address, price_feed.address, market_registry.address,
        )
    assert cm_addr != "0x" + "00" * 20
    assert collateral_manager_factory.cm_count() == 1
    assert collateral_manager_factory.cm_by_market(condition_id) == cm_addr
    assert collateral_manager_factory.cm_list(0) == cm_addr


def test_deploy_cm_non_owner_reverts(collateral_manager_factory, lender, condition_id, mock_ctf, price_feed, market_registry):
    with boa.reverts():
        with boa.env.prank(lender):
            collateral_manager_factory.deploy_cm(
                condition_id, mock_ctf.address, price_feed.address, market_registry.address,
            )


def test_deploy_cm_duplicate_reverts(collateral_manager_factory, deployer, condition_id, mock_ctf, price_feed, market_registry):
    with boa.env.prank(deployer):
        collateral_manager_factory.deploy_cm(
            condition_id, mock_ctf.address, price_feed.address, market_registry.address,
        )

    with boa.reverts("cm exists"):
        with boa.env.prank(deployer):
            collateral_manager_factory.deploy_cm(
                condition_id, mock_ctf.address, price_feed.address, market_registry.address,
            )


def test_set_implementation(collateral_manager_factory, deployer):
    new_bp = boa.load_partial("contracts/collateral/CollateralManager.vy").deploy_as_blueprint()
    with boa.env.prank(deployer):
        collateral_manager_factory.set_implementation(new_bp.address)
    assert collateral_manager_factory.implementation() == new_bp.address


def test_set_implementation_non_owner_reverts(collateral_manager_factory, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            collateral_manager_factory.set_implementation(lender)


def test_set_implementation_empty_reverts(collateral_manager_factory, deployer):
    with boa.reverts("empty implementation"):
        with boa.env.prank(deployer):
            collateral_manager_factory.set_implementation("0x" + "00" * 20)
