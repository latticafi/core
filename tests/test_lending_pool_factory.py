import boa


def test_initial_state(lending_pool_factory, lending_pool_blueprint, deployer):
    assert lending_pool_factory.implementation() == lending_pool_blueprint.address
    assert lending_pool_factory.pool_count() == 0
    assert lending_pool_factory.owner() == deployer


def test_deploy_pool(
    lending_pool_factory, deployer, condition_id,
    mock_usdc, collateral_manager, premium_oracle,
    interest_rate_model, market_registry, price_feed,
):
    with boa.env.prank(deployer):
        pool_addr = lending_pool_factory.deploy_pool(
            condition_id,
            mock_usdc.address,
            collateral_manager.address,
            premium_oracle.address,
            interest_rate_model.address,
            market_registry.address,
            price_feed.address,
            86400,
            604800,
        )
    assert pool_addr != "0x" + "00" * 20
    assert lending_pool_factory.pool_count() == 1
    assert lending_pool_factory.pool_by_market(condition_id) == pool_addr
    assert lending_pool_factory.pool_list(0) == pool_addr


def test_deploy_pool_non_owner_reverts(
    lending_pool_factory, lender, condition_id,
    mock_usdc, collateral_manager, premium_oracle,
    interest_rate_model, market_registry, price_feed,
):
    with boa.reverts():
        with boa.env.prank(lender):
            lending_pool_factory.deploy_pool(
                condition_id,
                mock_usdc.address,
                collateral_manager.address,
                premium_oracle.address,
                interest_rate_model.address,
                market_registry.address,
                price_feed.address,
                86400,
                604800,
            )


def test_deploy_pool_duplicate_reverts(
    lending_pool_factory, deployer, condition_id,
    mock_usdc, collateral_manager, premium_oracle,
    interest_rate_model, market_registry, price_feed,
):
    with boa.env.prank(deployer):
        lending_pool_factory.deploy_pool(
            condition_id,
            mock_usdc.address,
            collateral_manager.address,
            premium_oracle.address,
            interest_rate_model.address,
            market_registry.address,
            price_feed.address,
            86400,
            604800,
        )

    with boa.reverts("pool exists"):
        with boa.env.prank(deployer):
            lending_pool_factory.deploy_pool(
                condition_id,
                mock_usdc.address,
                collateral_manager.address,
                premium_oracle.address,
                interest_rate_model.address,
                market_registry.address,
                price_feed.address,
                86400,
                604800,
            )


def test_set_implementation(lending_pool_factory, deployer):
    new_bp = boa.load_partial("contracts/lending/LendingPool.vy").deploy_as_blueprint()
    with boa.env.prank(deployer):
        lending_pool_factory.set_implementation(new_bp.address)
    assert lending_pool_factory.implementation() == new_bp.address


def test_set_implementation_non_owner_reverts(lending_pool_factory, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            lending_pool_factory.set_implementation(lender)


def test_set_implementation_empty_reverts(lending_pool_factory, deployer):
    with boa.reverts("empty implementation"):
        with boa.env.prank(deployer):
            lending_pool_factory.set_implementation("0x" + "00" * 20)
