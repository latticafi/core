import boa


def test_initial_state(price_feed_factory, price_feed_blueprint, deployer):
    assert price_feed_factory.implementation() == price_feed_blueprint.address
    assert price_feed_factory.feed_count() == 0
    assert price_feed_factory.owner() == deployer


def test_deploy_feed(price_feed_factory, deployer, pricer, condition_id):
    with boa.env.prank(deployer):
        feed_addr = price_feed_factory.deploy_feed(
            condition_id,
            pricer,
            200,
            3600,
            3000,
            600,
        )
    assert feed_addr != "0x" + "00" * 20
    assert price_feed_factory.feed_count() == 1
    assert price_feed_factory.feed_by_market(condition_id) == feed_addr
    assert price_feed_factory.feed_list(0) == feed_addr


def test_deploy_feed_non_owner_reverts(
    price_feed_factory, lender, pricer, condition_id
):
    with boa.reverts():
        with boa.env.prank(lender):
            price_feed_factory.deploy_feed(
                condition_id,
                pricer,
                200,
                3600,
                3000,
                600,
            )


def test_deploy_feed_duplicate_reverts(
    price_feed_factory, deployer, pricer, condition_id
):
    with boa.env.prank(deployer):
        price_feed_factory.deploy_feed(condition_id, pricer, 200, 3600, 3000, 600)

    with boa.reverts("feed exists"):
        with boa.env.prank(deployer):
            price_feed_factory.deploy_feed(condition_id, pricer, 200, 3600, 3000, 600)


def test_set_implementation(price_feed_factory, deployer, price_feed_blueprint):
    new_bp = boa.load_partial(
        "contracts/oracle/pricefeed/PriceFeed.vy"
    ).deploy_as_blueprint()
    with boa.env.prank(deployer):
        price_feed_factory.set_implementation(new_bp.address)
    assert price_feed_factory.implementation() == new_bp.address


def test_set_implementation_non_owner_reverts(price_feed_factory, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            price_feed_factory.set_implementation(lender)


def test_set_implementation_empty_reverts(price_feed_factory, deployer):
    with boa.reverts("empty implementation"):
        with boa.env.prank(deployer):
            price_feed_factory.set_implementation("0x" + "00" * 20)
