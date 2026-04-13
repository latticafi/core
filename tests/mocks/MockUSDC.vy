# pragma version ~=0.4.0

"""
@title Mock USDC
@notice Snekmate ERC20 configured as USDC for testing.
"""

from snekmate.auth import ownable
from snekmate.tokens import erc20

initializes: ownable
initializes: erc20[ownable := ownable]

exports: (
    erc20.totalSupply,
    erc20.balanceOf,
    erc20.allowance,
    erc20.name,
    erc20.symbol,
    erc20.decimals,
    erc20.transfer,
    erc20.approve,
    erc20.transferFrom,
    erc20.owner,
)


@deploy
def __init__():
    ownable.__init__()
    erc20.__init__("USD Coin", "USDC", 6, "USD Coin", "1")


@external
def mint(_to: address, _amount: uint256):
    """Unrestricted mint for testing."""
    erc20._mint(_to, _amount)
