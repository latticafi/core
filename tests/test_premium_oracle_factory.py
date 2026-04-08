import boa


def test_initial_state(premium_oracle_factory, premium_oracle_blueprint, deployer):
    assert premium_oracle_factory.implementation() == premium_oracle_blueprint.address
    assert premium_oracle_factory.oracle_count() == 0
    assert premium_oracle_factory.owner() == deployer


def test_deploy_oracle(premium_oracle_factory, deployer, pricer, condition_id):
    with boa.env.prank(deployer):
        oracle_addr = premium_oracle_factory.deploy_oracle(condition_id, pricer)
    assert oracle_addr != "0x" + "00" * 20
    assert premium_oracle_factory.oracle_count() == 1
    assert premium_oracle_factory.oracle_by_market(condition_id) == oracle_addr
    assert premium_oracle_factory.oracle_list(0) == oracle_addr


def test_deploy_oracle_non_owner_reverts(
    premium_oracle_factory, lender, pricer, condition_id
):
    with boa.reverts():
        with boa.env.prank(lender):
            premium_oracle_factory.deploy_oracle(condition_id, pricer)


def test_deploy_oracle_duplicate_reverts(
    premium_oracle_factory, deployer, pricer, condition_id
):
    with boa.env.prank(deployer):
        premium_oracle_factory.deploy_oracle(condition_id, pricer)

    with boa.reverts("oracle already exists"):
        with boa.env.prank(deployer):
            premium_oracle_factory.deploy_oracle(condition_id, pricer)


def test_set_implementation(premium_oracle_factory, deployer):
    new_bp = boa.load_partial(
        "contracts/oracle/premium/PremiumOracle.vy"
    ).deploy_as_blueprint()
    with boa.env.prank(deployer):
        premium_oracle_factory.set_implementation(new_bp.address)
    assert premium_oracle_factory.implementation() == new_bp.address


def test_set_implementation_non_owner_reverts(premium_oracle_factory, lender):
    with boa.reverts():
        with boa.env.prank(lender):
            premium_oracle_factory.set_implementation(lender)


def test_set_implementation_empty_reverts(premium_oracle_factory, deployer):
    with boa.reverts("invalid implementation"):
        with boa.env.prank(deployer):
            premium_oracle_factory.set_implementation("0x" + "00" * 20)
