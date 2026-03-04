"""
Integration tests — full lifecycle flows.

NOTE: Gasless execution and Safe wallet deployment are off-chain
(Polymarket Builder Relayer). These tests use direct contract calls,
which are functionally equivalent to what the relayer submits on
behalf of Safe wallets. See conftest.py for wallet context notes.

Covers:
- Happy path: deposit → borrow → repay before cutoff → withdraw
- Roll path: borrow → roll at epoch end → repay next epoch
- Roll blocked: next epoch would cross cutoff → must repay
- Liquidation path: price drops → liquidation → pool recovers
- Cutoff expiry: loan not repaid by cutoff → forced liquidation
- Multi-lender, multi-borrower in same epoch
- Multiple markets with different cutoffs in same pool
- WARBIRD premium update mid-epoch (does not affect existing loans,
  only new loans in next epoch)
- PriceFeed circuit breaker trips → new loans paused → breaker
  resets → lending resumes

Accounting model:
- Interest rate computed from utilization curve at origination
- Interest collected at origination → pool yield → lender shares appreciate
- Premium collected at origination → reserve (not lender yield)
- Utilization increases after borrow → next loan pays higher rate
- Liquidation shortfall → deducted from reserve
- Reserve surplus after clean epoch → stays in reserve
- Governance triggers reserve surplus distribution → lenders receive bonus
- Multiple epochs: reserve accumulates, interest compounds

Market registry:
- Borrow on non-whitelisted market → reverts
- Admin onboards market → borrow succeeds
- Admin pauses market → new loans blocked, existing settle normally
- Market exposure cap reached → new borrows for that market blocked,
  other markets still open

Existing position scenarios (Path A: "Connect Wallet"):
- Borrower already holds CTF tokens (pre-funded in fixture) →
  posts as collateral without any prior Lattica interaction
- Borrower holds positions across multiple markets →
  posts from different conditionIds as collateral
- Borrower holds both YES and NO tokens → only posts YES side
  (the side they want to borrow against)

Approval scenarios:
- Borrower without CTF approval on CollateralManager → reverts
- Borrower approves CollateralManager → can post collateral
- Lender without USDC.e approval on LendingPool → reverts
- Lender approves LendingPool → can deposit
"""
