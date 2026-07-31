pragma solidity ^0.8.0;
// a line comment
/* a block
   comment */
abstract contract Base { uint256 public x; }

interface IThing { function ping() external returns (bool); }

library L { function add(uint a, uint b) internal pure returns (uint) { return a + b; } }

contract Demo is Base, IThing {
    uint256 public counter;
    mapping(address => uint) balances;
    address payable owner;

    modifier onlyOwner() { require(msg.sender == owner); _; }

    constructor() { owner = payable(msg.sender); }

    function ping() external override returns (bool) { return true; }

    function complex(uint a, uint b, address to) public onlyOwner returns (uint) {
        if (a > b) {
            for (uint i = 0; i < a; i++) {
                if (b == 0) { revert(); } else { balances[to] += 1; }
                while (b > 10) { b--; }
            }
        } else if (a == b) { b = L.add(a, b); }
        else { try IThing(to).ping() returns (bool ok) { b = ok ? 1 : 2; } catch { b = 3; } }
        return a > b ? a : b;
    }
}
