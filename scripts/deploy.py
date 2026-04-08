"""
Deploy Lattica core contracts.

Usage:
    uv run python scripts/deploy.py local polymarket
    vlt run --env=dev -- uv run python scripts/deploy.py amoy polymarket
    vlt run --env=prod -- uv run python scripts/deploy.py polygon polymarket
"""

import argparse
import os
import sys
from pathlib import Path

import boa
import yaml
from eth_account import Account

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_DIR = ROOT / "settings"
CHAIN_DIR = SETTINGS_DIR / "chain"
MARKET_DIR = SETTINGS_DIR / "market"
DEPLOYMENTS_DIR = ROOT / "deployments"


def load_yaml(path):
    if not path.exists():
        available = sorted(f.stem for f in path.parent.glob("*.yaml"))
        print(f"ERROR: {path} not found.")
        if available:
            print(f"Available: {', '.join(available)}")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def save_deployment(chain_name, addresses):
    DEPLOYMENTS_DIR.mkdir(exist_ok=True)
    out = DEPLOYMENTS_DIR / f"{chain_name}.yaml"
    with open(out, "w") as f:
        yaml.dump(addresses, f, default_flow_style=False)
    print(f"Deployment saved to {out}")


def deploy(chain, market):
    chain_cfg = load_yaml(CHAIN_DIR / f"{chain}.yaml")
    market_cfg = load_yaml(MARKET_DIR / f"{market}.yaml")
    lattica_cfg = load_yaml(SETTINGS_DIR / "lattica.yaml")

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
                "Run via: vlt run --env=dev -- uv run python scripts/deploy.py <chain> <market>"
            )
            sys.exit(1)

        boa.set_network_env(rpc_url)
        account = Account.from_key(deployer_key)
        boa.env.add_account(account)
        boa.env.eoa = account.address

    print(f"  Chain:    {chain} ({chain_cfg['chain_id']})")
    print(f"  Market:   {market}")
    print(f"  USDC.e:   {chain_cfg.get('usdc_e', 'N/A')}")
    print(f"  CTF:      {market_cfg.get('ctf', 'N/A')}")
    print(
        f"  Cutoff:   {lattica_cfg.get('resolution_cutoff_buffer', 'N/A')}s before resolution"
    )

    address_provider = boa.load("contracts/registry/AddressProvider.vy")
    market_registry = boa.load("contracts/market/MarketRegistry.vy")
    interest_model = boa.load(
        "contracts/lending/InterestRateModel.vy",
        lattica_cfg["interest_base_rate_bps"],
        lattica_cfg["interest_optimal_utilization_bps"],
        lattica_cfg["interest_slope1_bps"],
        lattica_cfg["interest_slope2_bps"],
    )
    pool_views = boa.load("contracts/lending/LendingPoolViews.vy")

    pf_bp = boa.load_partial(
        "contracts/oracle/pricefeed/PriceFeed.vy"
    ).deploy_as_blueprint()
    po_bp = boa.load_partial(
        "contracts/oracle/premium/PremiumOracle.vy"
    ).deploy_as_blueprint()
    cm_bp = boa.load_partial(
        "contracts/collateral/CollateralManager.vy"
    ).deploy_as_blueprint()
    lp_bp = boa.load_partial("contracts/lending/LendingPool.vy").deploy_as_blueprint()
    liq_bp = boa.load_partial(
        "contracts/liquidation/Liquidator.vy"
    ).deploy_as_blueprint()

    pf_factory = boa.load(
        "contracts/oracle/pricefeed/factory/PriceFeedFactory.vy", pf_bp.address
    )
    po_factory = boa.load(
        "contracts/oracle/premium/factory/PremiumOracleFactory.vy", po_bp.address
    )
    cm_factory = boa.load(
        "contracts/collateral/factory/CollateralManagerFactory.vy", cm_bp.address
    )
    lp_factory = boa.load(
        "contracts/lending/factory/LendingPoolFactory.vy", lp_bp.address
    )
    liq_factory = boa.load(
        "contracts/liquidation/factory/LiquidatorFactory.vy", liq_bp.address
    )

    address_provider.set_address(0, lp_factory.address)
    address_provider.set_address(1, cm_factory.address)
    address_provider.set_address(2, liq_factory.address)
    address_provider.set_address(3, pf_factory.address)
    address_provider.set_address(4, po_factory.address)
    address_provider.set_address(5, market_registry.address)
    address_provider.set_address(6, interest_model.address)
    address_provider.set_address(7, pool_views.address)
    address_provider.set_address(8, chain_cfg["usdc_e"])
    address_provider.set_address(9, market_cfg[chain]["ctf"])

    save_deployment(
        chain,
        {
            "address_provider": str(address_provider.address),
            "market_registry": str(market_registry.address),
            "interest_rate_model": str(interest_model.address),
            "lending_pool_views": str(pool_views.address),
            "lending_pool_factory": str(lp_factory.address),
            "collateral_manager_factory": str(cm_factory.address),
            "liquidator_factory": str(liq_factory.address),
            "price_feed_factory": str(pf_factory.address),
            "premium_oracle_factory": str(po_factory.address),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Lattica core contracts")
    parser.add_argument("chain", help="Chain name (e.g. local, amoy, polygon)")
    parser.add_argument("market", help="Market name (e.g. polymarket)")
    args = parser.parse_args()
    deploy(args.chain, args.market)
