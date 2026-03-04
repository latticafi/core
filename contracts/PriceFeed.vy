# @version ^0.4.3

"""
@title Price Feed
@notice Real-time VWAP price feed for CTF outcome tokens.
        Used by CollateralManager for health factor calculation
        and by Liquidator for trigger checks.
@dev    Design principles (bootstrapped — no Chainlink for CTF tokens):

        WHY BOOTSTRAPPED:
        No oracle service (Chainlink, Pyth, RedStone) carries price
        feeds for per-market CTF outcome tokens. The source of truth
        is the Polymarket CLOB orderbook. Any oracle would just be
        reading from the same place our backend does.

        METHODOLOGY: VWAP
        - Backend computes VWAP over a rolling window from Polymarket
          CLOB data and pushes on-chain.
        - VWAP is harder to manipulate than spot — requires sustained
          volume, not a single fill. Mitigates Mango Markets-style
          thin-book manipulation where an attacker pumps collateral
          value with a single large fill.

        UPDATE MECHANISM: Deviation-based
        - Backend pushes a new price when VWAP moves > threshold
          (e.g. 2%) from last on-chain value.
        - Reacts fast to real moves, doesn't waste gas on noise.
        - Staleness check: if no update in N seconds, price is stale
          and cannot be used for new borrows (existing positions can
          still be liquidated using the stale price — conservative).

        CIRCUIT BREAKERS:
        - If price moves > Y% within Z blocks, circuit breaker trips.
        - During circuit breaker: no new loans. Liquidations still
          execute (using last known price — protects the pool).
        - Since lending is cut off before resolution, any extreme
          move during active lending is likely manipulation, not
          real resolution. This simplifies the circuit breaker.

        SAFETY (Mango-style attack mitigation):
        - Max collateral per market caps exposure — even if price is
          manipulated, damage is bounded.
        - Only authorized updater can push prices.
        - Price bounded to [0, 1e18] (outcome token is worth 0-1 USDC.e).

        INTERFACE: IPriceFeed.vyi
        - Swappable implementation. If Chainlink/Pyth/UMA ever add
          CTF feeds, swap the backend without changing consumers.
"""
