"""
Config loader for Lattica deployments.
"""

import os
from dataclasses import dataclass

from eth_account import Account

CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"


@dataclass
class DeployConfig:
    deployer_private_key: str
    rpc_url: str
    chain_id: int
    pricer_address: str
    oracle_signer_address: str
    operator_address: str
    usdc_address: str | None = None

    @property
    def deployer(self) -> str:
        return Account.from_key(self.deployer_private_key).address


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ValueError(f"Missing: {key} (are you running under `vlt run`?)")
    return val


def load_config(mock_usdc: bool = False) -> DeployConfig:
    cfg = DeployConfig(
        deployer_private_key=_require("DEPLOYER_PRIVATE_KEY"),
        rpc_url=_require("RPC_URL"),
        chain_id=int(_require("CHAIN_ID")),
        pricer_address=_require("PRICER_ADDRESS"),
        oracle_signer_address=_require("ORACLE_SIGNER_ADDRESS"),
        operator_address=_require("OPERATOR_ADDRESS"),
    )
    if not mock_usdc:
        cfg.usdc_address = _require("USDC_ADDRESS")
    return cfg
