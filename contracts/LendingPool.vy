# @version ^0.4.3

"""
@title Lending Pool
@notice Lending pool for prediction market loans.
        Lenders deposit USDC.e and earn yield from borrower interest.
        Borrowers post CTF outcome tokens as collateral and pay an
        interest rate (market-driven via utilization curve) plus a
        risk premium (priced by WARBIRD) upfront for the epoch.
@dev    Key properties:
        - NOT an ERC4626 vault — epoch-based with fixed pricing.
        - Lenders deposit/withdraw USDC.e. Withdrawals may queue if
          utilization is high.
        - Borrowers borrow USDC.e against CTF collateral. Interest +
          premium deducted at origination.
        - No loans can be opened after the resolution cutoff.
        - All loans expire at min(epoch_end, cutoff). No loan ever
          crosses a market resolution.
        - At expiry: borrower repays, rolls (if next epoch fits
          before cutoff), or gets liquidated.

        ACCOUNTING MODEL (three balances):

        1. AVAILABLE LIQUIDITY
           = total_deposits - active_borrows
           What can be lent out or withdrawn right now.

        2. ACCRUED INTEREST (lender yield)
           Rate determined by utilization curve at loan origination.
           Deducted from borrower at origination → added to pool.
           Appreciates lender shares pro-rata.
           This IS the lender's return.

        3. PREMIUM RESERVE (risk buffer)
           Per-(conditionId, epoch) premium set by WARBIRD model.
           Deducted from borrower at origination → goes to reserve.
           Does NOT go to lenders directly.
           Purpose: absorb liquidation shortfalls.
             - Liquidation recovers less than debt → shortfall
               covered from reserve.
             - Epoch closes cleanly → surplus stays in reserve.
           Reserve surplus disposition (governance decision):
             a) Stay in reserve (grow buffer over time)
             b) Distribute to lenders as bonus yield
             c) Send to protocol treasury
             d) Some combination of the above

        INTEREST RATE MODEL (utilization curve):
        Market-driven. Rate is a function of pool utilization:
          utilization = total_borrowed / total_deposited

        Kinked curve (Aave/Compound model):
          - Below optimal utilization (e.g. 80%):
            rate = base_rate + utilization * slope1
            Gentle slope — encourages borrowing.
          - Above optimal utilization:
            rate = base_rate + optimal * slope1
                 + (utilization - optimal) * slope2
            Steep slope — aggressively discourages over-borrowing,
            attracts new lender deposits.

        Curve parameters (governance-tunable):
          - base_rate_bps: floor rate when pool is empty
          - optimal_utilization_bps: kink point (e.g. 8000 = 80%)
          - slope1_bps: rate of increase below kink
          - slope2_bps: rate of increase above kink (steep)

        Rate is computed at the moment of loan origination and locked
        for that loan's lifetime (the epoch). No mid-epoch rate changes
        on existing loans.

        Self-adjusting equilibrium:
          - Pool under-utilized → low rate → attracts borrowers
          - Pool over-utilized → high rate → attracts lenders,
            discourages borrowers, withdrawal queue pressure eases

        WHY SEPARATE (interest vs premium):
        If premiums went straight to lenders, there's no loss buffer.
        The premium IS the insurance. The interest is the yield.
        Separating them gives clean accounting:
          - Lenders know their yield (utilization-driven, transparent).
          - Reserve health is visible on-chain.
          - Governance can tune curve params (demand) independently of
            premium (risk) — they serve different purposes.

        FUTURE: EPOCH AUCTION / CLEARING RATE

        The utilization curve is the v1 interest rate mechanism. A more
        capital-efficient approach for a future version is an epoch
        auction (clearing rate book):

        1. Before each epoch opens, a short auction window runs.
        2. Lenders submit supply offers: "I'll lend X USDC.e at ≥ Y% rate"
        3. Borrowers submit demand bids: "I'll borrow X USDC.e at ≤ Y% rate"
        4. Auction clears: uniform clearing rate where supply meets demand.
           All lenders above the clearing rate are filled (earn clearing rate).
           All borrowers below the clearing rate are filled (pay clearing rate).
        5. Unfilled orders are returned. Epoch goes live.

        Advantages over utilization curve:
          - True price discovery — rate set by actual supply/demand, not a
            governance-tuned formula.
          - No kink parameter tuning — the market finds equilibrium.
          - Lenders can express rate preferences, not just deposit blindly.
          - Better capital efficiency — no idle capital at wrong rates.

        Disadvantages:
          - Requires coordination phase before each epoch (latency).
          - Thin order books could produce volatile rates.
          - More complex smart contract (order matching on-chain or
            commit-reveal off-chain with on-chain settlement).
          - UX overhead — lenders and borrowers must actively participate
            in the auction window rather than passively depositing.

        Implementation path:
          - v1: utilization curve (current). Simple, proven, no coordination.
          - v2: optional auction mode per market. Markets with enough
            two-sided interest graduate to auction pricing. Others stay
            on utilization curve.
          - The LendingPool interface (deposit/borrow/repay/withdraw)
            stays the same. Only the rate determination changes.

        CAPITAL ALLOCATION:
        Single pool model. All lender deposits are fungible.
        Per-market exposure capped by EpochManager's market registry
        (max_exposure_cap per conditionId). Borrower calls
        borrow(conditionId, amount) → pool checks:
          1. Market is whitelisted (registered in EpochManager)
          2. Market is not past resolution cutoff
          3. Available liquidity >= amount
          4. Market exposure cap not exceeded
          5. PriceFeed is not stale and circuit breaker not tripped
        If all pass → compute interest rate from utilization curve →
        deduct interest + premium at origination → transfer USDC.e
        to borrower's Safe.

        Lenders are effectively buying the "Lattica curated basket" —
        they trust admin's market selection + WARBIRD's pricing.
        Isolated per-market pools can be added later if needed.

        WALLET INTEGRATION:
        - All user addresses are Safe wallets (Gnosis Safe).
        - Two onboarding paths produce the same Safe type:
          Path A: browser wallet (MetaMask etc) → deterministic Safe
          Path B: Privy email/social → embedded EOA → deterministic Safe
        - The Safe must have USDC.e approved for this pool (ERC20 approve).
        - Approval is batched with Polymarket's standard approvals
          during user session setup (via Builder Relayer, gasless).
        - All txs can be routed through Polymarket's Builder Relayer
          for gasless execution. The contracts themselves don't need
          gasless awareness — the relayer submits standard txs.
"""
