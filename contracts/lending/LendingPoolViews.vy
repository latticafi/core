# pragma version ~=0.4.3

interface ILendingPool:
    def total_deposits() -> uint256: view
    def total_borrowed() -> uint256: view
    def premium_reserve() -> uint256: view
    def total_shares() -> uint256: view
    def shares(_lender: address) -> uint256: view
    def pool_state() -> uint256: view


@view
@external
def get_utilization(pool: address) -> uint256:
    deposits: uint256 = staticcall ILendingPool(pool).total_deposits()
    if deposits == 0:
        return 0
    borrowed: uint256 = staticcall ILendingPool(pool).total_borrowed()
    return (borrowed * 10000) // deposits


@view
@external
def get_available_liquidity(pool: address) -> uint256:
    deposits: uint256 = staticcall ILendingPool(pool).total_deposits()
    borrowed: uint256 = staticcall ILendingPool(pool).total_borrowed()
    return deposits - borrowed


@view
@external
def get_lender_value(pool: address, lender: address) -> uint256:
    total_shares: uint256 = staticcall ILendingPool(pool).total_shares()
    if total_shares == 0:
        return 0
    lender_shares: uint256 = staticcall ILendingPool(pool).shares(lender)
    deposits: uint256 = staticcall ILendingPool(pool).total_deposits()
    return (lender_shares * deposits) // total_shares
