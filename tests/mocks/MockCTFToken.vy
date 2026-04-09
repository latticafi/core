# pragma version ~=0.4.0

"""
@title Mock CTF Token
@notice Snekmate ERC1155 configured as Polymarket conditional token for testing.
"""

from snekmate.auth import ownable
from snekmate.tokens import erc1155

initializes: ownable
initializes: erc1155[ownable := ownable]

exports: (
    erc1155.safeTransferFrom,
    erc1155.safeBatchTransferFrom,
    erc1155.balanceOf,
    erc1155.balanceOfBatch,
    erc1155.setApprovalForAll,
    erc1155.isApprovedForAll,
    erc1155.supportsInterface,
    erc1155.owner,
    erc1155.uri,
)


@deploy
def __init__():
    ownable.__init__()
    erc1155.__init__("")


@external
def mint(_to: address, _id: uint256, _amount: uint256):
    """Unrestricted mint for testing."""
    erc1155._safe_mint(_to, _id, _amount, b"")
