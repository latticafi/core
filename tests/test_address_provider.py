import boa


def test_owner_is_deployer(address_provider, deployer):
    assert address_provider.owner() == deployer


def test_set_address(address_provider, deployer):
    addr = boa.env.generate_address("some_addr")
    with boa.env.prank(deployer):
        address_provider.set_address(0, addr)
    assert address_provider.get_address(0) == addr


def test_set_address_updates_max_id(address_provider, deployer):
    addr = boa.env.generate_address("some_addr")
    with boa.env.prank(deployer):
        address_provider.set_address(0, addr)
        address_provider.set_address(1, addr)
        address_provider.set_address(2, addr)
    assert address_provider.max_id() == 3


def test_set_address_non_owner_reverts(address_provider, lender):
    addr = boa.env.generate_address("some_addr")
    with boa.env.prank(lender):
        with boa.reverts():
            address_provider.set_address(0, addr)


def test_get_address_unset_reverts(address_provider):
    with boa.reverts("address not set"):
        address_provider.get_address(0)


def test_set_address_overwrites(address_provider, deployer):
    addr1 = boa.env.generate_address("addr1")
    addr2 = boa.env.generate_address("addr2")
    with boa.env.prank(deployer):
        address_provider.set_address(0, addr1)
        address_provider.set_address(0, addr2)
    assert address_provider.get_address(0) == addr2
