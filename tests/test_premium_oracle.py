import boa
import pytest
from eth_account import Account as EthAccount

PRICER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
OTHER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def sign_premium_quote(
    pricer_key,
    oracle_address,
    borrower,
    condition_id,
    premium_bps,
    amount,
    deadline,
    nonce,
    chain_id=1,
):
    domain_data = {
        "name": "LatticaPremiumOracle",
        "version": "1",
        "chainId": chain_id,
        "verifyingContract": oracle_address,
    }
    message_types = {
        "PremiumQuote": [
            {"name": "borrower", "type": "address"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "premiumBps", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
        ],
    }
    message_data = {
        "borrower": borrower,
        "conditionId": "0x" + condition_id.hex()
        if isinstance(condition_id, bytes)
        else condition_id,
        "premiumBps": premium_bps,
        "amount": amount,
        "deadline": deadline,
        "nonce": nonce,
    }
    signed = EthAccount.sign_typed_data(
        pricer_key,
        domain_data=domain_data,
        message_types=message_types,
        message_data=message_data,
    )
    return signed.signature


@pytest.fixture(scope="session")
def test_borrower():
    acc = boa.env.generate_address("test_borrower")
    boa.env.set_balance(acc, 10 * 10**18)
    return acc


def test_initial_state(premium_oracle, condition_id, pricer):
    assert premium_oracle.condition_id() == condition_id
    assert premium_oracle.authorized_pricer() == pricer
    assert premium_oracle.DOMAIN_SEPARATOR() != b"\x00" * 32


def test_verify_and_consume_valid(
    premium_oracle, pricer, deployer, test_borrower, condition_id
):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    premium_bps = 500
    amount = 10_000 * 10**6
    deadline = 2_000_000_000
    nonce = premium_oracle.get_nonce(test_borrower)

    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        premium_bps,
        amount,
        deadline,
        nonce,
    )

    with boa.env.prank(mock_pool):
        result = premium_oracle.verify_and_consume(
            test_borrower, premium_bps, amount, deadline, sig
        )

    assert result == premium_bps
    assert premium_oracle.get_nonce(test_borrower) == 1


def test_verify_and_consume_expired_reverts(premium_oracle, deployer, test_borrower):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    deadline = 1
    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        500,
        10_000 * 10**6,
        deadline,
        0,
    )

    with boa.reverts("quote expired"):
        with boa.env.prank(mock_pool):
            premium_oracle.verify_and_consume(
                test_borrower, 500, 10_000 * 10**6, deadline, sig
            )


def test_verify_and_consume_wrong_signer_reverts(
    premium_oracle, deployer, test_borrower
):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    sig = sign_premium_quote(
        OTHER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        500,
        10_000 * 10**6,
        2_000_000_000,
        0,
    )

    with boa.reverts("invalid signer"):
        with boa.env.prank(mock_pool):
            premium_oracle.verify_and_consume(
                test_borrower, 500, 10_000 * 10**6, 2_000_000_000, sig
            )


def test_verify_and_consume_replay_reverts(premium_oracle, deployer, test_borrower):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        500,
        10_000 * 10**6,
        2_000_000_000,
        0,
    )

    with boa.env.prank(mock_pool):
        premium_oracle.verify_and_consume(
            test_borrower, 500, 10_000 * 10**6, 2_000_000_000, sig
        )

    with boa.reverts("invalid signer"):
        with boa.env.prank(mock_pool):
            premium_oracle.verify_and_consume(
                test_borrower, 500, 10_000 * 10**6, 2_000_000_000, sig
            )


def test_verify_and_consume_wrong_amount_reverts(
    premium_oracle, deployer, test_borrower
):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        500,
        10_000 * 10**6,
        2_000_000_000,
        0,
    )

    with boa.reverts("invalid signer"):
        with boa.env.prank(mock_pool):
            premium_oracle.verify_and_consume(
                test_borrower, 500, 20_000 * 10**6, 2_000_000_000, sig
            )


def test_verify_and_consume_not_pool_reverts(premium_oracle, lender, test_borrower):
    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        500,
        10_000 * 10**6,
        2_000_000_000,
        0,
    )

    with boa.reverts("not authorized"):
        with boa.env.prank(lender):
            premium_oracle.verify_and_consume(
                test_borrower, 500, 10_000 * 10**6, 2_000_000_000, sig
            )


def test_verify_and_consume_premium_exceeds_max_reverts(
    premium_oracle, deployer, test_borrower
):
    mock_pool = boa.env.generate_address("mock_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(mock_pool)

    sig = sign_premium_quote(
        PRICER_KEY,
        premium_oracle.address,
        test_borrower,
        premium_oracle.condition_id(),
        10001,
        10_000 * 10**6,
        2_000_000_000,
        0,
    )

    with boa.reverts("premium exceeds max"):
        with boa.env.prank(mock_pool):
            premium_oracle.verify_and_consume(
                test_borrower, 10001, 10_000 * 10**6, 2_000_000_000, sig
            )


def test_set_authorized_pricer(premium_oracle, deployer):
    new_pricer = boa.env.generate_address("new_pricer")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pricer(new_pricer)
    assert premium_oracle.authorized_pricer() == new_pricer


def test_set_authorized_pool(premium_oracle, deployer):
    new_pool = boa.env.generate_address("new_pool")
    with boa.env.prank(deployer):
        premium_oracle.set_authorized_pool(new_pool)
    assert premium_oracle.authorized_pool() == new_pool


def test_get_nonce_starts_at_zero(premium_oracle, test_borrower):
    assert premium_oracle.get_nonce(test_borrower) == 0
