"""
Config loader for Lattica deployments.
"""

import os
from dataclasses import dataclass

from eth_account import Account


@dataclass
class DeployConfig:
    deployer_private_key: str
    rpc_url: str
    chain_id: int
    pricer_address: str
    oracle_signer_address: str
    operator_address: str
    usdc_address: str
    ctf_address: str

    @property
    def deployer(self) -> str:
        return Account.from_key(self.deployer_private_key).address


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ValueError(f"Missing: {key} (are you running under `vlt run`?)")
    return val


def load_config() -> DeployConfig:
    return DeployConfig(
        deployer_private_key=_require("DEPLOYER_PRIVATE_KEY"),
        rpc_url=_require("RPC_URL"),
        chain_id=int(_require("CHAIN_ID")),
        pricer_address=_require("PRICER_ADDRESS"),
        oracle_signer_address=_require("ORACLE_SIGNER_ADDRESS"),
        operator_address=_require("OPERATOR_ADDRESS"),
        usdc_address=_require("USDC_ADDRESS"),
        ctf_address=_require("CTF_ADDRESS"),
    )
