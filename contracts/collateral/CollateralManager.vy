# pragma version ~=0.4.3

from snekmate.auth import access_control

initializes: access_control

exports: (
    access_control.hasRole,
    access_control.getRoleAdmin,
    access_control.grantRole,
    access_control.revokeRole,
    access_control.renounceRole,
    access_control.set_role_admin,
    access_control.supportsInterface,
    access_control.DEFAULT_ADMIN_ROLE,
)

interface ICTF:
    def safeTransferFrom(_from: address, _to: address, _id: uint256, _amount: uint256, _data: Bytes[1024]): nonpayable
    def balanceOf(_account: address, _id: uint256) -> uint256: view

interface IPriceFeed:
    def get_price() -> (uint256, bool): view

interface IMarketRegistry:
    def get_market_params(condition_id: bytes32) -> (uint256, uint256, uint256, uint256, uint256, bool, bool): view

struct Position:
    amount: uint256
    token_id: uint256
    debt: uint256

event CollateralDeposited:
    borrower: address
    amount: uint256
    token_id: uint256

event CollateralReleased:
    borrower: address
    amount: uint256

event CollateralSeized:
    borrower: address
    amount: uint256

POOL_ROLE: constant(bytes32) = keccak256("POOL_ROLE")
LIQUIDATOR_ROLE: constant(bytes32) = keccak256("LIQUIDATOR_ROLE")
HEALTH_PRECISION: constant(uint256) = 10000
MAX_BPS: constant(uint256) = 10000
PRICE_PRECISION: constant(uint256) = 10 ** 18

condition_id: public(bytes32)
ctf: public(address)
price_feed: public(address)
market_registry: public(address)
positions: public(HashMap[address, Position])
total_collateral: public(uint256)

@deploy
def __init__(
    _condition_id: bytes32,
    _ctf: address,
    _price_feed: address,
    _market_registry: address,
):
    access_control.__init__()
    assert _ctf != empty(address), "empty ctf"
    assert _price_feed != empty(address), "empty price_feed"
    assert _market_registry != empty(address), "empty market_registry"
    self.condition_id = _condition_id
    self.ctf = _ctf
    self.price_feed = _price_feed
    self.market_registry = _market_registry

@nonreentrant
@external
def deposit_collateral(borrower: address, amount: uint256, token_id: uint256):
    access_control._check_role(POOL_ROLE, msg.sender)
    assert amount > 0, "zero amount"
    assert self.positions[borrower].amount == 0, "position exists"
    extcall ICTF(self.ctf).safeTransferFrom(borrower, self, token_id, amount, b"")
    self.positions[borrower] = Position(
        amount=amount,
        token_id=token_id,
        debt=0,
    )
    self.total_collateral += amount
    log CollateralDeposited(borrower=borrower, amount=amount, token_id=token_id)

@nonreentrant
@external
def release_collateral(borrower: address):
    access_control._check_role(POOL_ROLE, msg.sender)
    pos: Position = self.positions[borrower]
    assert pos.amount > 0, "no position"
    extcall ICTF(self.ctf).safeTransferFrom(self, borrower, pos.token_id, pos.amount, b"")
    self.total_collateral -= pos.amount
    self.positions[borrower] = empty(Position)
    log CollateralReleased(borrower=borrower, amount=pos.amount)

@nonreentrant
@external
def seize_collateral(borrower: address) -> uint256:
    access_control._check_role(LIQUIDATOR_ROLE, msg.sender)
    pos: Position = self.positions[borrower]
    assert pos.amount > 0, "no position"
    seized: uint256 = pos.amount
    extcall ICTF(self.ctf).safeTransferFrom(self, msg.sender, pos.token_id, seized, b"")
    self.total_collateral -= seized
    self.positions[borrower] = empty(Position)
    log CollateralSeized(borrower=borrower, amount=seized)
    return seized

@external
def set_debt(borrower: address, debt: uint256):
    access_control._check_role(POOL_ROLE, msg.sender)
    assert self.positions[borrower].amount > 0, "no position"
    self.positions[borrower].debt = debt

@view
@external
def get_health_factor(borrower: address) -> uint256:
    pos: Position = self.positions[borrower]
    if pos.amount == 0 or pos.debt == 0:
        return max_value(uint256)
    price: uint256 = 0
    is_stale: bool = False
    price, is_stale = staticcall IPriceFeed(self.price_feed).get_price()
    if price == 0:
        return 0
    params: (uint256, uint256, uint256, uint256, uint256, bool, bool) = staticcall IMarketRegistry(self.market_registry).get_market_params(self.condition_id)
    collateral_factor: uint256 = params[0]
    collateral_value: uint256 = (pos.amount * price) // PRICE_PRECISION
    adjusted_value: uint256 = (collateral_value * collateral_factor) // MAX_BPS
    health: uint256 = (adjusted_value * HEALTH_PRECISION) // pos.debt
    return health

@external
def onERC1155Received(
    _operator: address,
    _sender: address,
    _token_id: uint256,
    _amount: uint256,
    _data: Bytes[1024],
) -> bytes4:
    return 0xf23a6e61

@external
def onERC1155BatchReceived(
    _operator: address,
    _sender: address,
    _token_ids: DynArray[uint256, 65535],
    _amounts: DynArray[uint256, 65535],
    _data: Bytes[1024],
) -> bytes4:
    return 0xbc197c81
