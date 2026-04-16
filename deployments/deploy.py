"""
Deploy Lattica protocol stack.
"""

import json
import os
import sys

import boa
import requests
from config import CTF, load_config
from eth_account import Account


def deploy_mock_usdc() -> str:
    usdc = boa.load("tests/mocks/MockUSDC.vy")
    print(f"  MockUSDC:              {usdc.address}")
    return usdc.address


def deploy_stack(cfg, usdc_address: str) -> dict:
    pool = boa.load("contracts/LendingPool.vy", usdc_address, CTF, cfg.deployer)
    print(f"  LendingPool:           {pool.address}")

    core = boa.load("contracts/PoolCore.vy", usdc_address, pool.address, cfg.deployer)
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
        usdc_address,
        pool.address,
        cfg.deployer,
        100_000 * 10**6,
        1000,
        3000,
    )
    print(f"  Reserve:               {reserve.address}")

    pool.initialize(core.address, reserve.address, cfg.oracle_signer_address, cfg.operator_address)
    print("  LendingPool initialized")

    return {
        "chain_id": cfg.chain_id,
        "usdc": usdc_address,
        "ctf": CTF,
        "pool": pool.address,
        "core": core.address,
        "oracle": oracle.address,
        "controller": controller.address,
        "reserve": reserve.address,
        "owner": cfg.deployer,
        "operator": cfg.operator_address,
        "pricer": cfg.pricer_address,
        "oracle_signer": cfg.oracle_signer_address,
    }


def push_addresses_to_vault(addresses: dict, env: str):
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if not vault_addr or not vault_token:
        print("  VAULT_ADDR/VAULT_TOKEN not set, skipping vault push")
        return

    url = f"{vault_addr}/v1/secret/data/{env}/addresses"
    resp = requests.put(
        url,
        headers={"X-Vault-Token": vault_token},
        json={"data": addresses},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"  Addresses pushed to vault (secret/data/{env}/addresses)")


def main():
    dry_run = "--dry-run" in sys.argv
    mock_usdc = "--mock-usdc" in sys.argv
    env = os.environ.get("DEPLOY_ENV", "staging")

    cfg = load_config(mock_usdc=mock_usdc)

    if dry_run:
        print("[DRY RUN] Forking locally...")
        boa.fork(cfg.rpc_url, block_identifier="latest")
        boa.env.eoa = cfg.deployer
    else:
        print("[BROADCAST] Deploying to chain...")
        acct = Account.from_key(cfg.deployer_private_key)
        boa.set_network_env(cfg.rpc_url)
        boa.env.add_account(acct, force_eoa=True)

    if mock_usdc:
        usdc_address = deploy_mock_usdc()
    else:
        assert cfg.usdc_address is not None
        usdc_address = cfg.usdc_address

    print(f"\nDeploying (chain={cfg.chain_id}, usdc={usdc_address}, ctf={CTF})...")
    addresses = deploy_stack(cfg, usdc_address)

    outfile = f"deployments/addresses-{cfg.chain_id}.json"
    with open(outfile, "w") as f:
        json.dump(addresses, f, indent=2)
    print(f"Addresses saved to {outfile}")

    if not dry_run:
        push_addresses_to_vault(addresses, env)


if __name__ == "__main__":
    main()
