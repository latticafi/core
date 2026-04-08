# pragma version ~=0.4.3

balanceOf: public(HashMap[address, HashMap[uint256, uint256]])
isApprovedForAll: public(HashMap[address, HashMap[address, bool]])


@deploy
def __init__():
    pass


@external
def mint(to: address, token_id: uint256, amount: uint256):
    self.balanceOf[to][token_id] += amount


@external
def setApprovalForAll(operator: address, approved: bool):
    self.isApprovedForAll[msg.sender][operator] = approved


@external
def safeTransferFrom(
    _from: address,
    _to: address,
    _id: uint256,
    _amount: uint256,
    _data: Bytes[1024],
):
    assert (
        self.isApprovedForAll[_from][msg.sender] or msg.sender == _from
    ), "not approved"
    assert self.balanceOf[_from][_id] >= _amount, "insufficient balance"
    self.balanceOf[_from][_id] -= _amount
    self.balanceOf[_to][_id] += _amount
