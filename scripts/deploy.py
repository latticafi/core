"""
Deploy Lattica core contracts.

Usage:
    uv run python scripts/deploy.py local polymarket
    infisical run --env=dev -- uv run python scripts/deploy.py amoy polymarket
    infisical run --env=prod -- uv run python scripts/deploy.py polygon polymarket
"""

import argparse
import os
import sys
from pathlib import Path
from eth_account import Account

import yaml

import boa

ROOT = Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "chain"
MARKET_DIR = ROOT / "market"
SETTINGS_DIR = ROOT / "settings"
DEPLOYMENTS_DIR = ROOT / "deployments"


def load_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        print(f"ERROR: Missing required secret {key}")
        sys.exit(1)
    return value


def load_yaml(path):
    if not path.exists():
        available = sorted(f.stem for f in path.parent.glob("*.yaml"))
        print(f"ERROR: {path} not found.")
        if available:
            print(f"Available: {', '.join(available)}")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def save_deployment(chain_name: str, addresses: dict) -> None:
    DEPLOYMENTS_DIR.mkdir(exist_ok=True)
    out = DEPLOYMENTS_DIR / f"{chain_name}.yaml"
    with open(out, "w") as f:
        yaml.dump(addresses, f, default_flow_style=False)
    print(f"Deployment saved to {out}")


def deploy(chain, market):
    chain_config = load_yaml(CHAIN_DIR / f"{chain}.yaml")
    market_config = load_yaml(MARKET_DIR / f"{market}.yaml")
    lattica_config = load_yaml(SETTINGS_DIR / "lattica.yaml")

    if chain == "local":
        print("Deploying to local pyevm...")
    else:
        rpc_url = os.environ.get("RPC_URL")
        deployer_key = os.environ.get("DEPLOYER_PRIVATE_KEY")
        if not rpc_url or not deployer_key:
            print(
                "ERROR: RPC_URL and DEPLOYER_PRIVATE_KEY required for non-local deploy."
            )
            print(
                "Run via: infisical run --env=dev -- uv run python scripts/deploy.py <chain> <market>"
            )
            sys.exit(1)

        boa.set_network_env(rpc_url)
        account = Account.from_key(deployer_key)
        boa.env.add_account(account)
        boa.env.eoa = account.address

    print(f"  Chain:    {chain} ({chain_config['chain_id']})")
    print(f"  Market:   {market}")
    print(f"  USDC.e:   {chain_config.get('usdc_e', 'N/A')}")
    print(f"  CTF:      {market_config.get('ctf', 'N/A')}")
    print(
        f"  Cutoff:   {lattica_config.get('resolution_cutoff_buffer', 'N/A')}s before resolution"
    )

    # Deploy sequence (6 contracts):
    #
    # Config sources:
    #   chain:   usdc_e
    #   market:  ctf, ctf_exchange, neg_risk_ctf_exchange, relayer
    #   lattica: epoch duration, cutoff buffer, interest curve, price feed
    #
    # 1. EpochManager(admin, default_epoch_duration, resolution_cutoff_buffer)
    #    - Admin-gated market registry. Markets must be onboarded before
    #      any other contract will accept their conditionId.
    #    - Per-market params: collateral_factor, max_exposure_cap,
    #      min_liquidity_depth, resolution_time → cutoff.
    # 2. PremiumOracle(authorized_pricer=backend_wallet, reveal_delay=N)
    #    - Premiums go to pool's premium reserve, not to lenders.
    # 3. PriceFeed(authorized_updater=backend_wallet, deviation_threshold, staleness_limit, circuit_breaker_threshold)
    # 4. CollateralManager(ctf, epoch_manager, price_feed)
    #    - ctf address from market config.
    #    - Reads collateral_factor + max_exposure_cap from EpochManager.
    # 5. LendingPool(usdc_e, epoch_manager, premium_oracle, collateral_manager, curve_params)
    #    - usdc_e from chain config. curve_params from lattica config.
    #    - Three-part accounting: available liquidity, accrued interest
    #      (→ lender yield), premium reserve (→ risk buffer).
    #    - Interest rate: utilization curve (base_rate, optimal_utilization,
    #      slope1, slope2). Governance-tunable params, market-driven rate.
    # 6. Liquidator(pool, collateral_manager, price_feed, ctf_exchange, neg_risk_ctf_exchange)
    #    - Exchange addresses from market config.
    #    - Shortfalls covered from premium reserve.
    #
    # Wire permissions:
    #    - pool → collateral_manager (can seize on liquidation)
    #    - liquidator → collateral_manager (can seize)
    #    - liquidator → pool (can return recovered USDC.e)
    #    - liquidator needs ERC1155 approval on CTF for ctf_exchange
    #    - liquidator needs ERC1155 approval on CTF for neg_risk_ctf_exchange
    #
    # Gasless: NOT deployed on-chain. The backend routes user txs through
    # the market's relayer using HMAC auth with Builder credentials.
    # Users interact via Safe wallets deployed through the relayer.
    #
    # USER-SIDE APPROVALS (batched during session setup, via RelayClient):
    # These are NOT done in this deploy script — they happen per-user in
    # the frontend when a user first connects. Added to the standard
    # market approval batch:
    #    - USDC.e → LendingPool (so pool can pull USDC.e for deposits)
    #    - USDC.e → CollateralManager (so CM can pull premium payments)
    #    - CTF (ERC1155) → CollateralManager (so CM can pull collateral)
    print("(contracts not implemented yet)")

    # save_deployment(chain_name, {
    #     "lending_pool": str(pool.address),
    #     "epoch_manager": str(epoch.address),
    #     "premium_oracle": str(oracle.address),
    #     "price_feed": str(pf.address),
    #     "collateral_manager": str(cm.address),
    #     "liquidator": str(liq.address),
    # })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Lattica core contracts")
    parser.add_argument("chain", help="Chain name (e.g. local, amoy, polygon)")
    parser.add_argument("market", help="Market name (e.g. polymarket)")
    args = parser.parse_args()
    deploy(args.chain, args.market)
