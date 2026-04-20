"""
Deploy Lattica protocol stack.
"""

import json
import os
import sys

import boa
import requests
from config import CTF, CTF_EXCHANGE, NEG_RISK_ADAPTER, NEG_RISK_CTF_EXCHANGE, load_config
from eth_account import Account
from vyper.compiler.output import build_abi_output
from web3 import Web3


def _compile(source_path: str) -> tuple[list, str]:
    """Compile via boa (resolves snekmate), return (abi, bytecode)."""
    deployer = boa.load_partial(source_path)
    abi = build_abi_output(deployer.compiler_data)
    bytecode = deployer.compiler_data.bytecode
    return abi, bytecode


def _deploy_w3(w3: Web3, acct, source_path: str, *constructor_args) -> tuple[str, list]:
    """Deploy a contract via web3.py. Returns (address, abi)."""
    abi, bytecode = _compile(source_path)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor(*constructor_args).build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    assert receipt["status"] == 1, f"deploy failed: {source_path}"
    addr = receipt["contractAddress"]
    assert addr is not None, f"no contract address in receipt: {source_path}"
    addr = str(addr)
    print(f"  {source_path.split('/')[-1].replace('.vy', ''):24} {addr}")
    return addr, abi


def _call_w3(w3: Web3, acct, addr: str, abi: list, fn_name: str, *args):
    """Call a state-changing function via web3.py."""
    contract = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
    fn = getattr(contract.functions, fn_name)(*args)
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    assert receipt["status"] == 1, f"{fn_name} failed"
    print(f"  {fn_name} OK")


def _make_addresses(
    cfg,
    usdc_address: str,
    pool: str,
    core: str,
    oracle: str,
    controller: str,
    reserve: str,
    views: str,
    owner: str,
) -> dict:
    """Build addresses dict with keys matching rest-api deploy workflow."""
    return {
        "CHAIN_ID": cfg.chain_id,
        "USDC_ADDRESS": usdc_address,
        "CTF_ADDRESS": CTF,
        "CTF_EXCHANGE": CTF_EXCHANGE,
        "NEG_RISK_CTF_EXCHANGE": NEG_RISK_CTF_EXCHANGE,
        "NEG_RISK_ADAPTER": NEG_RISK_ADAPTER,
        "POOL_ADDRESS": pool,
        "CORE_ADDRESS": core,
        "ORACLE_ADDRESS": oracle,
        "CONTROLLER_ADDRESS": controller,
        "RESERVE_ADDRESS": reserve,
        "VIEWS_ADDRESS": views,
        "OWNER": owner,
        "OPERATOR_ADDRESS": cfg.operator_address,
        "PRICER_ADDRESS": cfg.pricer_address,
        "ORACLE_SIGNER_ADDRESS": cfg.oracle_signer_address,
    }


def deploy_broadcast(cfg, usdc_address: str | None) -> dict:
    """Deploy all contracts via web3.py."""
    w3 = Web3(Web3.HTTPProvider(cfg.rpc_url))
    acct = Account.from_key(cfg.deployer_private_key)
    assert w3.is_connected(), "RPC not reachable"
    print(f"  Balance: {w3.from_wei(w3.eth.get_balance(acct.address), 'ether')} POL\n")

    if usdc_address is None:
        usdc_address, _ = _deploy_w3(w3, acct, "tests/mocks/MockUSDC.vy")

    pool, pool_abi = _deploy_w3(
        w3, acct, "contracts/LendingPool.vy", usdc_address, CTF, acct.address
    )

    core, core_abi = _deploy_w3(w3, acct, "contracts/PoolCore.vy", usdc_address, pool, acct.address)

    oracle, _ = _deploy_w3(
        w3, acct, "contracts/PremiumOracle.vy", cfg.pricer_address, core, acct.address
    )

    controller, _ = _deploy_w3(
        w3, acct, "contracts/PortfolioController.vy", core, acct.address, 10_000_000 * 10**6
    )

    _call_w3(w3, acct, core, core_abi, "set_peripherals", oracle, controller)

    reserve, _ = _deploy_w3(
        w3,
        acct,
        "contracts/Reserve.vy",
        usdc_address,
        pool,
        acct.address,
        100_000 * 10**6,
        1000,
        3000,
    )

    views, _ = _deploy_w3(w3, acct, "contracts/Views.vy", pool, core, controller, reserve)

    _call_w3(
        w3,
        acct,
        pool,
        pool_abi,
        "initialize",
        core,
        reserve,
        cfg.oracle_signer_address,
        cfg.operator_address,
    )

    return _make_addresses(
        cfg, usdc_address, pool, core, oracle, controller, reserve, views, acct.address
    )


def deploy_dryrun(cfg, usdc_address: str | None) -> dict:
    """Deploy via boa fork (no gas, local only)."""
    boa.fork(cfg.rpc_url, block_identifier="latest")
    boa.env.eoa = cfg.deployer

    if usdc_address is None:
        usdc = boa.load("tests/mocks/MockUSDC.vy")
        usdc_address = usdc.address
        print(f"  {'MockUSDC':24} {usdc_address}")

    pool = boa.load("contracts/LendingPool.vy", usdc_address, CTF, cfg.deployer)
    print(f"  {'LendingPool':24} {pool.address}")

    core = boa.load("contracts/PoolCore.vy", usdc_address, pool.address, cfg.deployer)
    print(f"  {'PoolCore':24} {core.address}")

    oracle = boa.load("contracts/PremiumOracle.vy", cfg.pricer_address, core.address, cfg.deployer)
    print(f"  {'PremiumOracle':24} {oracle.address}")

    controller = boa.load(
        "contracts/PortfolioController.vy", core.address, cfg.deployer, 10_000_000 * 10**6
    )
    print(f"  {'PortfolioController':24} {controller.address}")

    core.set_peripherals(oracle.address, controller.address)
    print("  set_peripherals OK")

    reserve = boa.load(
        "contracts/Reserve.vy",
        usdc_address,
        pool.address,
        cfg.deployer,
        100_000 * 10**6,
        1000,
        3000,
    )
    print(f"  {'Reserve':24} {reserve.address}")

    views = boa.load(
        "contracts/Views.vy", pool.address, core.address, controller.address, reserve.address
    )
    print(f"  {'Views':24} {views.address}")

    pool.initialize(core.address, reserve.address, cfg.oracle_signer_address, cfg.operator_address)
    print("  initialize OK")

    return _make_addresses(
        cfg,
        usdc_address,
        pool.address,
        core.address,
        oracle.address,
        controller.address,
        reserve.address,
        views.address,
        cfg.deployer,
    )


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

    print(f"chain:                          {cfg.chain_id}")
    print(f"deployer:                       {cfg.deployer}")
    print(f"mode:                           {'dry-run' if dry_run else 'broadcast'}")
    print(f"usdc:                           {'mock' if mock_usdc else cfg.usdc_address}")
    print(f"ctf:                            {CTF}")
    print(f"ctf_exchange:                   {CTF_EXCHANGE}")
    print(f"neg_risk_ctf_exchange:          {NEG_RISK_CTF_EXCHANGE}")
    print(f"neg_risk_adapter:               {NEG_RISK_ADAPTER}")
    print(f"env:                            {env}")

    usdc_address: str | None = None
    if not mock_usdc:
        assert cfg.usdc_address is not None
        usdc_address = cfg.usdc_address

    if dry_run:
        print("\n[DRY RUN] Forking locally...")
        addresses = deploy_dryrun(cfg, usdc_address)
    else:
        print("\n[BROADCAST] Deploying to chain...")
        addresses = deploy_broadcast(cfg, usdc_address)

    outfile = f"deployments/addresses-{cfg.chain_id}.json"
    with open(outfile, "w") as f:
        json.dump(addresses, f, indent=2)
    print(f"\nAddresses saved to {outfile}")

    if not dry_run:
        push_addresses_to_vault(addresses, env)


if __name__ == "__main__":
    main()
