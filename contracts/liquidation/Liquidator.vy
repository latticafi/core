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

interface ILendingPool:
    def loans(_borrower: address) -> (uint256, uint256, uint256, uint256, uint256, bool): view
    def handle_liquidation_proceeds(_borrower: address, _recovered: uint256): nonpayable

interface ICollateralManager:
    def seize_collateral(_borrower: address) -> uint256: nonpayable
    def get_health_factor(_borrower: address) -> uint256: view
    def positions(_borrower: address) -> (uint256, uint256, uint256): view

interface IPriceFeed:
    def get_price() -> (uint256, bool): view

interface IERC20:
    def transfer(_to: address, _amount: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _amount: uint256) -> bool: nonpayable
    def balanceOf(_account: address) -> uint256: view
    def approve(_spender: address, _amount: uint256) -> bool: nonpayable

interface ICTF:
    def safeTransferFrom(_from: address, _to: address, _id: uint256, _amount: uint256, _data: Bytes[1024]): nonpayable

event Liquidated:
    borrower: address
    seized: uint256
    to_pool: uint256
    fee: uint256

event LiquidationFeeUpdated:
    new_fee: uint256

HEALTH_THRESHOLD: constant(uint256) = 10000
MAX_BPS: constant(uint256) = 10000
PRICE_PRECISION: constant(uint256) = 10 ** 18

condition_id: public(bytes32)
lending_pool: public(address)
collateral_manager: public(address)
price_feed: public(address)
usdc_e: public(address)
ctf: public(address)
liquidation_fee_bps: public(uint256)


@deploy
def __init__(
    _condition_id: bytes32,
    _lending_pool: address,
    _collateral_manager: address,
    _price_feed: address,
    _usdc_e: address,
    _ctf: address,
    _liquidation_fee_bps: uint256,
):
    access_control.__init__()
    assert _lending_pool != empty(address), "empty lending_pool"
    assert _collateral_manager != empty(address), "empty collateral_manager"
    assert _price_feed != empty(address), "empty price_feed"
    assert _usdc_e != empty(address), "empty usdc_e"
    assert _ctf != empty(address), "empty ctf"
    assert _liquidation_fee_bps <= MAX_BPS, "fee exceeds max"
    self.condition_id = _condition_id
    self.lending_pool = _lending_pool
    self.collateral_manager = _collateral_manager
    self.price_feed = _price_feed
    self.usdc_e = _usdc_e
    self.ctf = _ctf
    self.liquidation_fee_bps = _liquidation_fee_bps


@nonreentrant
@external
def liquidate(borrower: address):
    assert self._is_liquidatable(borrower), "not liquidatable"

    pos_data: (uint256, uint256, uint256) = staticcall ICollateralManager(
        self.collateral_manager
    ).positions(borrower)
    token_id: uint256 = pos_data[1]

    loan_data: (uint256, uint256, uint256, uint256, uint256, bool) = staticcall ILendingPool(
        self.lending_pool
    ).loans(borrower)
    principal: uint256 = loan_data[0]

    seized: uint256 = extcall ICollateralManager(
        self.collateral_manager
    ).seize_collateral(borrower)

    price: uint256 = 0
    is_stale: bool = False
    price, is_stale = staticcall IPriceFeed(self.price_feed).get_price()
    collateral_value: uint256 = (seized * price) // PRICE_PRECISION

    fee: uint256 = (collateral_value * self.liquidation_fee_bps) // MAX_BPS
    to_pool: uint256 = collateral_value - fee
    if to_pool > principal:
        to_pool = principal

    extcall IERC20(self.usdc_e).transferFrom(msg.sender, self, to_pool)
    extcall IERC20(self.usdc_e).approve(self.lending_pool, to_pool)
    extcall ILendingPool(self.lending_pool).handle_liquidation_proceeds(
        borrower, to_pool
    )

    extcall ICTF(self.ctf).safeTransferFrom(self, msg.sender, token_id, seized, b"")

    log Liquidated(borrower=borrower, seized=seized, to_pool=to_pool, fee=fee)


@view
@external
def is_liquidatable(borrower: address) -> bool:
    return self._is_liquidatable(borrower)


@view
@internal
def _is_liquidatable(borrower: address) -> bool:
    loan_data: (uint256, uint256, uint256, uint256, uint256, bool) = staticcall ILendingPool(
        self.lending_pool
    ).loans(borrower)
    is_active: bool = loan_data[5]
    if not is_active:
        return False

    epoch_end: uint256 = loan_data[4]
    if block.timestamp > epoch_end:
        return True

    health: uint256 = staticcall ICollateralManager(
        self.collateral_manager
    ).get_health_factor(borrower)
    if health < HEALTH_THRESHOLD:
        return True

    return False


@external
def set_liquidation_fee(new_fee: uint256):
    access_control._check_role(access_control.DEFAULT_ADMIN_ROLE, msg.sender)
    assert new_fee <= MAX_BPS, "fee exceeds max"
    self.liquidation_fee_bps = new_fee
    log LiquidationFeeUpdated(new_fee=new_fee)


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
