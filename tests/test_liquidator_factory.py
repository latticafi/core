import boa


def test_initial_state(liquidator_factory, liquidator_blueprint, deployer):
    assert liquidator_factory.implementation() == liquidator_blueprint.address
    assert liquidator_factory.liq_count() == 0
    assert liquidator_factory.owner() == deployer


def test_deploy_liquidator(
    liquidator_factory,
    deployer,
    condition_id,
    lending_pool,
    collateral_manager,
    price_feed,
    mock_usdc,
    mock_ctf,
    setup_market,
):
    with boa.env.prank(deployer):
        liq_addr = liquidator_factory.deploy_liquidator(
            condition_id,
            lending_pool.address,
            collateral_manager.address,
            price_feed.address,
            mock_usdc.address,
            mock_ctf.address,
            500,
        )
    assert liq_addr != "0x" + "00" * 20
    assert liquidator_factory.liq_count() == 1
    assert liquidator_factory.liq_by_market(condition_id) == liq_addr
    assert liquidator_factory.liq_list(0) == liq_addr


def test_deploy_liquidator_non_owner_reverts(
    liquidator_factory,
    lender,
    condition_id,
    lending_pool,
    collateral_manager,
    price_feed,
    mock_usdc,
    mock_ctf,
    setup_market,
):
    with boa.reverts():
        with boa.env.prank(lender):
            liquidator_factory.deploy_liquidator(
                condition_id,
                lending_pool.address,
                collateral_manager.address,
                price_feed.address,
                mock_usdc.address,
                mock_ctf.address,
                500,
            )


def test_deploy_liquidator_duplicate_reverts(
    liquidator_factory,
    deployer,
    condition_id,
    lending_pool,
    collateral_manager,
    price_feed,
    mock_usdc,
    mock_ctf,
    setup_market,
):
    with boa.env.prank(deployer):
        liquidator_factory.deploy_liquidator(
            condition_id,
            lending_pool.address,
            collateral_manager.address,
            price_feed.address,
            mock_usdc.address,
            mock_ctf.address,
            500,
        )

    with boa.reverts("liquidator exists"):
        with boa.env.prank(deployer):
            liquidator_factory.deploy_liquidator(
                condition_id,
                lending_pool.address,
                collateral_manager.address,
                price_feed.address,
                mock_usdc.address,
                mock_ctf.address,
                500,
            )


def test_set_implementation(liquidator_factory, deployer):
    new_bp = boa.load_partial(
        "contracts/liquidation/Liquidator.vy"
    ).deploy_as_blueprint()
    with boa.env.prank(deployer):
        liquidator_factory.set_implementation(new_bp.address)
    assert liquidator_factory.implementation() == new_bp.address


def test_set_implementation_non_owner_reverts(liquidator_factory, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            liquidator_factory.set_implementation(lender)


def test_set_implementation_empty_reverts(liquidator_factory, deployer):
    with boa.reverts("empty implementation"):
        with boa.env.prank(deployer):
            liquidator_factory.set_implementation("0x" + "00" * 20)
