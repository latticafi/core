"""
Deploy Lattica protocol stack.
"""

import json
import sys

import boa
from config import load_config


def deploy_stack(cfg) -> dict:
    pool = boa.load("contracts/LendingPool.vy", cfg.usdc_address, cfg.ctf_address, cfg.deployer)
    print(f"  LendingPool:           {pool.address}")

    core = boa.load("contracts/PoolCore.vy", cfg.usdc_address, pool.address, cfg.deployer)
    print(f"  PoolCore:              {core.address}")

    oracle = boa.load("contracts/PremiumOracle.vy", cfg.pricer_address, core.address, cfg.deployer)
    print(f"  PremiumOracle:         {oracle.address}")

    controller = boa.load(
        "contracts/PortfolioController.vy",
        core.address,
        cfg.deployer,
        10_000_000 * 10**6,
    )
    print(f"  PortfolioController:   {controller.address}")

    core.set_peripherals(oracle.address, controller.address)
    print("  PoolCore peripherals wired")

    reserve = boa.load(
        "contracts/Reserve.vy",
        cfg.usdc_address,
        pool.address,
        cfg.deployer,
        100_000 * 10**6,
        1000,
        3000,
    )
    print(f"  Reserve:               {reserve.address}")

    pool.initialize(core.address, reserve.address, cfg.oracle_signer_address, cfg.guardian_address)
    print("  LendingPool initialized")

    return {
        "chain_id": cfg.chain_id,
        "usdc": cfg.usdc_address,
        "ctf": cfg.ctf_address,
        "pool": pool.address,
        "core": core.address,
        "oracle": oracle.address,
        "controller": controller.address,
        "reserve": reserve.address,
        "admin": cfg.deployer,
        "guardian": cfg.guardian_address,
        "pricer": cfg.pricer_address,
        "oracle_signer": cfg.oracle_signer_address,
    }


def main():
    dry_run = "--dry-run" in sys.argv

    cfg = load_config()
    print(f"chain:     {cfg.chain_id}")
    print(f"deployer:  {cfg.deployer}")
    print(f"usdc:      {cfg.usdc_address}")
    print(f"ctf:       {cfg.ctf_address}")

    print("\nForking...")
    boa.env.fork(cfg.rpc_url)
    boa.env.eoa = cfg.deployer

    print("Deploying Lattica stack...")
    addresses = deploy_stack(cfg)

    outfile = f"deployments/addresses-{cfg.chain_id}.json"
    with open(outfile, "w") as f:
        json.dump(addresses, f, indent=2)
    print(f"\nAddresses saved to {outfile}")

    if dry_run:
        print("[DRY RUN] No transactions broadcast.")


if __name__ == "__main__":
    main()
