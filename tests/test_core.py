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
    sign_quote,
    submit_signed_price,
)

# Deposit / Withdraw


class TestDeposit:
    def test_deposit_mints_shares(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        assert shares > 0
        assert core.share_balance(lender) == shares
        assert core.total_shares() > 0

    def test_deposit_zero_reverts(self, pool, lender):
        with boa.env.prank(lender):
            with boa.reverts("zero amount"):
                pool.deposit(0)

    def test_deposit_when_paused_reverts(self, pool, usdc, lender, admin):
        usdc.mint(lender, 1_000 * 10**6)
        with boa.env.prank(admin):
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
    def test_withdraw_returns_usdc(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)

        balance_before = usdc.balanceOf(lender)
        with boa.env.prank(lender):
            amount = pool.withdraw(shares)

        assert amount > 0
        assert usdc.balanceOf(lender) == balance_before + amount
        assert core.share_balance(lender) == 0

    def test_withdraw_more_than_balance_reverts(self, pool, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            shares = pool.deposit(10_000 * 10**6)
        with boa.env.prank(lender):
            with boa.reverts("insufficient shares"):
                pool.withdraw(shares + 1)


# Borrow / Repay


class TestBorrow:
    @pytest.mark.usefixtures("funded")
    def test_borrow_creates_loan(self, pool, core, oracle, usdc, ctf_token, borrower_addr):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )

        usdc_before = usdc.balanceOf(borrower_addr)
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        loan = core.get_loan(loan_id)
        assert loan[0] == borrower_addr
        assert loan[4] == BORROW_AMOUNT
        assert loan[3] == COLLATERAL_AMOUNT
        assert not loan[11]
        assert not loan[12]
        assert usdc.balanceOf(borrower_addr) > usdc_before
        assert ctf_token.balanceOf(pool.address, TOKEN_ID) == COLLATERAL_AMOUNT
        assert ctf_token.balanceOf(borrower_addr, TOKEN_ID) == 0

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
            deadline,
            0,
            1,
        )
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
                )


class TestRepay:
    @pytest.mark.usefixtures("funded")
    def test_repay_returns_collateral(self, pool, core, oracle, ctf_token, borrower_addr):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        with boa.env.prank(borrower_addr):
            pool.repay(loan_id)

        loan = core.get_loan(loan_id)
        assert loan[11]
        assert ctf_token.balanceOf(borrower_addr, TOKEN_ID) == COLLATERAL_AMOUNT
        assert ctf_token.balanceOf(pool.address, TOKEN_ID) == 0
        assert core.total_borrowed() == 0

    @pytest.mark.usefixtures("funded")
    def test_repay_wrong_borrower_reverts(self, pool, oracle, borrower_addr, lender):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )
        with boa.env.prank(lender):
            with boa.reverts("not borrower"):
                pool.repay(loan_id)


# Roll


class TestRoll:
    @pytest.mark.usefixtures("funded")
    def test_roll_extends_loan(self, pool, core, oracle, borrower_addr):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            old_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        new_deadline = boa.env.evm.patch.timestamp + 7200
        sig2 = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            new_deadline,
            1,
            1,
        )
        with boa.env.prank(borrower_addr):
            new_id = pool.roll_loan(old_id, EPOCH_24H, PREMIUM_BPS, new_deadline, 1, sig2)

        old_loan = core.get_loan(old_id)
        new_loan = core.get_loan(new_id)
        assert old_loan[11]
        assert new_loan[0] == borrower_addr
        assert new_loan[4] == BORROW_AMOUNT
        assert new_loan[3] == COLLATERAL_AMOUNT


# Liquidation


class TestLiquidation:
    @pytest.mark.usefixtures("funded")
    def test_trigger_liquidation_on_underwater_loan(
        self,
        pool,
        core,
        oracle,
        ctf_token,
        deploy_stack,
        borrower_addr,
        liquidator,
    ):
        price_feed = deploy_stack["price_feed"]
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        # Crash price via signed attestation
        liq_price = core.get_liquidation_price(loan_id)
        crash_price = liq_price - 10**14
        boa.env.time_travel(seconds=1)
        submit_signed_price(price_feed, CONDITION_ID, crash_price)

        pool.trigger_liquidation(loan_id)

        loan = core.get_loan(loan_id)
        assert loan[12]
        assert core.total_borrowed() == 0
        assert ctf_token.balanceOf(liquidator.address, TOKEN_ID) == COLLATERAL_AMOUNT
        assert ctf_token.balanceOf(pool.address, TOKEN_ID) == 0

    @pytest.mark.usefixtures("funded")
    def test_trigger_healthy_loan_reverts(self, pool, oracle, borrower_addr):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )
        with boa.reverts("position is healthy"):
            pool.trigger_liquidation(loan_id)


class TestClaimExpired:
    @pytest.mark.usefixtures("funded")
    def test_claim_expired_after_epoch(
        self,
        pool,
        core,
        oracle,
        ctf_token,
        liquidator,
        borrower_addr,
    ):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        boa.env.time_travel(seconds=EPOCH_24H + 1)
        pool.claim_expired(loan_id)

        loan = core.get_loan(loan_id)
        assert loan[12]
        assert ctf_token.balanceOf(liquidator.address, TOKEN_ID) == COLLATERAL_AMOUNT

    @pytest.mark.usefixtures("funded")
    def test_claim_expired_before_epoch_reverts(self, pool, oracle, borrower_addr):
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )
        with boa.reverts("epoch not expired"):
            pool.claim_expired(loan_id)

    @pytest.mark.usefixtures("funded")
    def test_claim_nonexistent_loan_reverts(self, pool):
        with boa.reverts("loan does not exist"):
            pool.claim_expired(99999)


# Pause / Unpause


class TestPause:
    def test_guardian_can_pause(self, pool, guardian):
        with boa.env.prank(guardian):
            pool.pause()
        assert pool.paused()

    def test_guardian_cannot_unpause(self, pool, guardian, admin):
        with boa.env.prank(admin):
            pool.pause()
        with boa.env.prank(guardian):
            with boa.reverts("ownable: caller is not the owner"):
                pool.unpause()

    def test_owner_can_unpause(self, pool, admin):
        with boa.env.prank(admin):
            pool.pause()
            pool.unpause()
        assert not pool.paused()


# Share price


class TestSharePrice:
    def test_share_price_starts_at_one(self, pool, core, usdc, lender):
        usdc.mint(lender, 10_000 * 10**6)
        with boa.env.prank(lender):
            usdc.approve(pool.address, 2**256 - 1)
            pool.deposit(10_000 * 10**6)
        price = core.share_price()
        assert price >= 999_000
        assert price <= 1_001_000


# Liquidator settlement


class TestLiquidatorSettle:
    @pytest.mark.usefixtures("funded")
    def test_operator_settles_liquidation(
        self,
        pool,
        core,
        oracle,
        ctf_token,
        deploy_stack,
        borrower_addr,
        liquidator,
        liquidator_operator,
    ):
        price_feed = deploy_stack["price_feed"]
        deadline = boa.env.evm.patch.timestamp + 3600
        sig = sign_quote(
            oracle.address,
            borrower_addr,
            CONDITION_ID,
            PREMIUM_BPS,
            BORROW_AMOUNT,
            deadline,
            0,
            1,
        )
        with boa.env.prank(borrower_addr):
            loan_id = pool.borrow(
                CONDITION_ID,
                COLLATERAL_AMOUNT,
                BORROW_AMOUNT,
                EPOCH_24H,
                PREMIUM_BPS,
                deadline,
                0,
                sig,
            )

        liq_price = core.get_liquidation_price(loan_id)
        boa.env.time_travel(seconds=1)
        submit_signed_price(price_feed, CONDITION_ID, liq_price - 10**14)

        pool.trigger_liquidation(loan_id)
        assert liquidator.pending_count() == 1

        with boa.env.prank(liquidator_operator):
            liquidator.settle(loan_id, 200 * 10**6)

        assert liquidator.pending_count() == 0
        assert liquidator.total_recovered() == 200 * 10**6
