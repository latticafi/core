"""
Core functionality tests for Lattica protocol.
"""

import boa
import pytest

from conftest import (
    BORROW_AMOUNT,
    COLLATERAL_AMOUNT,
    CONDITION_ID,
    EPOCH_24H,
    PREMIUM_BPS,
    TOKEN_ID,
    make_price_params,
    sign_quote,
)


def _borrow(pool, oracle, borrower_addr, nonce=0):
    deadline = boa.env.evm.patch.timestamp + 3600
    sig = sign_quote(
        oracle.address,
        borrower_addr,
        CONDITION_ID,
        PREMIUM_BPS,
        BORROW_AMOUNT,
        COLLATERAL_AMOUNT,
        EPOCH_24H,
        deadline,
        nonce,
        1,
    )
    p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID)
    with boa.env.prank(borrower_addr):
        return pool.borrow(
            CONDITION_ID,
            COLLATERAL_AMOUNT,
            BORROW_AMOUNT,
            EPOCH_24H,
            PREMIUM_BPS,
            deadline,
            nonce,
            sig,
            p,
            pts,
            pd,
            psig,
        )


class TestDeposit:
    def test_deposit_mints_shares(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        assert shares > 0
        assert core.share_balance(lender) == shares

    def test_deposit_zero_reverts(self, pool, lender):
        with boa.env.prank(lender):
            with boa.reverts("zero amount"):
                pool.deposit(0)

    def test_deposit_when_paused_reverts(self, pool, usdc, lender, owner):
        usdc.mint(lender, 1_000 * 10**6)
        with boa.env.prank(owner):
            pool.pause()
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            with boa.reverts():
                pool.deposit(1_000 * 10**6)

    def test_first_deposit_burns_dead_shares(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        assert shares == 10_000 * 10**6 - 1000
        assert core.total_shares() == 10_000 * 10**6


class TestWithdraw:
    def test_withdraw_returns_usdc(self, pool, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        balance_before = usdc.balanceOf(lender)
        with boa.env.prank(lender):
            amount = pool.withdraw(shares)
        assert amount > 0
        assert usdc.balanceOf(lender) == balance_before + amount

    def test_withdraw_more_than_balance_reverts(self, pool, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        with boa.env.prank(lender):
            with boa.reverts("insufficient shares"):
                pool.withdraw(shares + 1)


class TestBorrow:
    @pytest.mark.usefixtures("funded")
    def test_borrow_creates_loan(self, pool, core, oracle, ctf_token, borrower_addr):
        loan_id = _borrow(pool, oracle, borrower_addr)
        loan = core.get_loan(loan_id)
        assert loan[0] == borrower_addr
        assert loan[4] == BORROW_AMOUNT
        assert loan[3] == COLLATERAL_AMOUNT
        assert not loan[11]
        assert not loan[12]
        assert ctf_token.balanceOf(pool.address, TOKEN_ID) == COLLATERAL_AMOUNT

    @pytest.mark.usefixtures("funded")
    def test_borrow_above_max_ltv_reverts(self, pool, oracle, borrower_addr):
        huge_borrow = 550 * 10**6
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            huge_borrow,
            COLLATERAL_AMOUNT,
            EPOCH_24H,
            deadline,
            0,
            1,
        )
        p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID)
        with boa.env.prank(borrower_addr):
            with boa.reverts("above max LTV"):
                pool.borrow(
                    CONDITION_ID,
                    COLLATERAL_AMOUNT,
                    huge_borrow,
                    EPOCH_24H,
                    PREMIUM_BPS,
                    deadline,
                    0,
                    sig,
                    p,
                    pts,
                    pd,
                    psig,
                )


class TestRepay:
    @pytest.mark.usefixtures("funded")
    def test_repay_returns_collateral(self, pool, core, oracle, ctf_token, borrower_addr):
        loan_id = _borrow(pool, oracle, borrower_addr)
        with boa.env.prank(borrower_addr):
            pool.repay(loan_id)
        loan = core.get_loan(loan_id)
        assert loan[11]
        assert ctf_token.balanceOf(borrower_addr, TOKEN_ID) == COLLATERAL_AMOUNT
        assert core.total_borrowed() == 0

    @pytest.mark.usefixtures("funded")
    def test_repay_wrong_borrower_reverts(self, pool, oracle, borrower_addr, lender):
        loan_id = _borrow(pool, oracle, borrower_addr)
        with boa.env.prank(lender):
            with boa.reverts("not borrower"):
                pool.repay(loan_id)


class TestRoll:
    @pytest.mark.usefixtures("funded")
    def test_roll_extends_loan(self, pool, core, oracle, borrower_addr):
        old_id = _borrow(pool, oracle, borrower_addr)

        new_deadline = boa.env.evm.patch.timestamp + 7200
        sig2 = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            COLLATERAL_AMOUNT,
            EPOCH_24H,
            new_deadline,
            1,
            1,
        )
        p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID)
        with boa.env.prank(borrower_addr):
            new_id = pool.roll_loan(
                old_id, EPOCH_24H, PREMIUM_BPS, new_deadline, 1, sig2, p, pts, pd, psig
            )

        assert core.get_loan(old_id)[11]  # old repaid
        assert core.get_loan(new_id)[0] == borrower_addr
        assert core.get_loan(new_id)[4] == BORROW_AMOUNT


class TestLiquidation:
    @pytest.mark.usefixtures("funded")
    def test_trigger_liquidation_on_underwater_loan(
        self, pool, core, oracle, ctf_token, borrower_addr, operator
    ):
        loan_id = _borrow(pool, oracle, borrower_addr)

        liq_price = core.get_liquidation_price(loan_id)
        crash_price = liq_price - 10**14
        p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID, crash_price)

        with boa.env.prank(operator):
            pool.trigger_liquidation(loan_id, p, pts, pd, psig)

        loan = core.get_loan(loan_id)
        assert loan[12]  # liquidated
        assert core.total_borrowed() == 0
        # Collateral transferred to operator (the caller)
        assert ctf_token.balanceOf(operator, TOKEN_ID) == COLLATERAL_AMOUNT
        assert ctf_token.balanceOf(pool.address, TOKEN_ID) == 0

    @pytest.mark.usefixtures("funded")
    def test_trigger_healthy_loan_reverts(self, pool, oracle, borrower_addr, operator):
        loan_id = _borrow(pool, oracle, borrower_addr)
        p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID)
        with boa.env.prank(operator):
            with boa.reverts("position is healthy"):
                pool.trigger_liquidation(loan_id, p, pts, pd, psig)

    @pytest.mark.usefixtures("funded")
    def test_trigger_liquidation_unauthorized_reverts(self, pool, oracle, borrower_addr):
        loan_id = _borrow(pool, oracle, borrower_addr)
        p, pts, pd, psig = make_price_params(pool.address, CONDITION_ID)
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not authorized"):
                pool.trigger_liquidation(loan_id, p, pts, pd, psig)


class TestClaimExpired:
    @pytest.mark.usefixtures("funded")
    def test_claim_expired_after_epoch(
        self, pool, core, oracle, ctf_token, borrower_addr, operator
    ):
        loan_id = _borrow(pool, oracle, borrower_addr)
        boa.env.time_travel(seconds=EPOCH_24H + 1)

        with boa.env.prank(operator):
            pool.claim_expired(loan_id)

        loan = core.get_loan(loan_id)
        assert loan[12]
        assert ctf_token.balanceOf(operator, TOKEN_ID) == COLLATERAL_AMOUNT

    @pytest.mark.usefixtures("funded")
    def test_claim_expired_before_epoch_reverts(self, pool, oracle, borrower_addr, operator):
        loan_id = _borrow(pool, oracle, borrower_addr)
        with boa.env.prank(operator):
            with boa.reverts("epoch not expired"):
                pool.claim_expired(loan_id)

    @pytest.mark.usefixtures("funded")
    def test_claim_nonexistent_loan_reverts(self, pool, operator):
        with boa.env.prank(operator):
            with boa.reverts("loan does not exist"):
                pool.claim_expired(99999)

    @pytest.mark.usefixtures("funded")
    def test_claim_expired_unauthorized_reverts(self, pool, oracle, borrower_addr):
        loan_id = _borrow(pool, oracle, borrower_addr)
        boa.env.time_travel(seconds=EPOCH_24H + 1)
        rando = boa.env.generate_address("rando")
        with boa.env.prank(rando):
            with boa.reverts("not authorized"):
                pool.claim_expired(loan_id)


class TestPause:
    def test_operator_can_pause(self, pool, operator):
        with boa.env.prank(operator):
            pool.pause()
        assert pool.paused()

    def test_operator_cannot_unpause(self, pool, operator, owner):
        with boa.env.prank(owner):
            pool.pause()
        with boa.env.prank(operator):
            with boa.reverts("ownable: caller is not the owner"):
                pool.unpause()

    def test_owner_can_unpause(self, pool, owner):
        with boa.env.prank(owner):
            pool.pause()
            pool.unpause()
        assert not pool.paused()


class TestSharePrice:
    def test_share_price_starts_at_one(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            pool.deposit(10_000 * 10**6)
        price = core.share_price()
        assert price >= 999_000
        assert price <= 1_001_000
