# @version ^0.4.3

"""
@title Epoch Premium Oracle
@notice On-chain source of truth for WARBIRD model premiums.
        Uses commit-reveal to prevent frontrunning.
@dev    WARBIRD = LightGBM (bulk features) + GPD/EVT (tail risk).
        Runs off-chain, produces a fixed premium per (conditionId, epoch).

        The premium prices RISK, not yield. It goes to the pool's
        premium reserve (not directly to lenders). The reserve absorbs
        liquidation shortfalls. Lender yield comes from the separate
        interest rate (utilization curve).

        Flow:
        1. Backend calls commit(conditionId, epoch, hash(premium, salt))
        2. After REVEAL_DELAY blocks, calls reveal(conditionId, epoch, premium, salt)
        3. Premium is active. LendingPool reads it at loan origination.

        EIP-712 signed quotes are supported for gasless borrow txs.
        Signed quotes MUST reference the on-chain revealed premium —
        contract verifies signature + checks quote matches revealed value.

        Authorized pricer is set by governance. Can be rotated.
        Premium is denominated in basis points of loan amount.
"""
