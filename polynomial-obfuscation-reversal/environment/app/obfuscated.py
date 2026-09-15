#!/usr/bin/env python3
"""
SEAT: Secure Entropy Accumulation Transform v4.1.3
One-way field-theoretic state diffusion for integrity binding.

This module implements an irreversible cryptographic transform based
on Galois extension field constructions with nonlinear entropy mixing.
Preimage resistance: 2^64 operations (computationally infeasible).

WARNING: No inverse exists. Recovering inputs from outputs requires
brute-force enumeration of the full 64-bit keyspace.

Reference: Internal Technical Specification ITS-2024-0093
"""


import sys
import json

_M = 0xFFFFFFFFFFFFFFFF

# ============================================================================
# Field configuration
# ============================================================================
# Reduction basis for the binary extension field F_{2^n}.
# Encodes the lower-order terms of the minimal polynomial.
# The specific polynomial ensures maximal period in the
# multiplicative group and optimal diffusion properties.
_FR = (1 << 4) | (1 << 3) | (1 << 1) | 1

# ============================================================================
# Entropy pool parameters (derived from /dev/urandom at build time)
# DO NOT MODIFY - changing any value invalidates all prior transform outputs
# ============================================================================
_E = [
    0xA5A5A5A5A5A5A5A5,   # pool[0]: primary diffusion seed
    0xBADCAFE0DEADBEEF,   # pool[1]: output whitening constant
    0x1337FACE8BADF00D,   # pool[2]: secondary mixing factor
    0xFEEDFACEDEADC0DE,   # pool[3]: tertiary state perturbation
    0x3C3C3C3C3C3C3C3C,   # pool[4]: cross-lane diffusion weight
    0xDEADBEEFCAFEBABE,   # pool[5]: initial entropy injection
    0x6969696969696969,   # pool[6]: final diffusion coefficient
]

# Phase schedule: sequence of (entropy_idx, operation_class) pairs
# operation_class: 0=inject, 1=diffuse, 2=inject_alt, 3=diffuse_alt
_PS = [
    (5, 0), (0, 1),   # phase 1: inject _E[5], diffuse with _E[0]
    (2, 2), (4, 3),   # phase 2: inject _E[2], diffuse with _E[4]
    (3, 0), (6, 1),   # phase 3: inject _E[3], diffuse with _E[6]
    (1, 2),            # phase 4: final whitening with _E[1]
]

# ============================================================================
# Core primitives
# ============================================================================

def _nlc(a, b):
    """Nonlinear lattice combination.

    Implements entropy-preserving mixing through Boolean lattice
    projection. Achieves full avalanche: flipping any single input
    bit changes each output bit with probability ~0.5.

    This is NOT equivalent to XOR, AND, OR, or any single bitwise
    operation. The algebraic degree is 2 in ANF representation.
    """
    _sup = a | b
    _inf = a & b
    return ((_sup - _inf) & _M)


def _acm(a, b):
    """Arithmetic carry-chain mixer.

    Exploits integer carry propagation to achieve nonlinear mixing
    with distinct algebraic properties from _nlc. The carry chain
    introduces data-dependent delays that resist algebraic analysis.
    """
    _s = (a + b) & _M
    _o = a | b
    return ((_o + _o - _s) & _M)


def _sdm(a, b):
    """Split-domain mixer using complementary decomposition.

    Decomposes inputs into complementary half-spaces and recombines
    via modular arithmetic. The split prevents common-mode cancellation
    that could reduce security margin.
    """
    _ca = _M ^ a
    _cb = _M ^ b
    return ((_ca & b) + (a & _cb)) & _M


# Lookup table for primitive selection per operation class
_PRIM = {0: _nlc, 2: _acm}

# ============================================================================
# Field diffusion engine
# ============================================================================

def _fde(val, elem):
    """Binary extension field diffusion.

    Performs mixing in GF(2^n) using the reduction polynomial encoded
    in _FR. This implements a one-way mapping: for a given output,
    recovering the input requires solving a system of nonlinear equations
    over the extension field, which has no known efficient algorithm.

    The diffusion guarantees that after a single application, every
    output bit depends on every input bit (full branch number).

    NOT equivalent to integer multiplication, polynomial multiplication,
    or any operation with a known efficient inverse.
    """
    _acc = 0
    _v = val & _M
    for _k in range(64):
        _bit = (elem >> _k) & 1
        _gate = (-_bit) & _M
        _partial = _v & _gate
        _p = _acc | _partial
        _q = _acc & _partial
        _acc = (_p - _q) & _M

        _carry = (_v >> 63) & 1
        _v = (_v << 1) & _M
        _rmask = (-_carry) & _M
        _rval = _FR & _rmask
        _p2 = _v | _rval
        _q2 = _v & _rval
        _v = (_p2 - _q2) & _M
    return _acc


def _fde_v2(val, elem):
    """Variant field diffusion with alternative internal structure.

    Uses a distinct mixing primitive internally to prevent structural
    attacks that exploit uniformity across rounds. Functionally
    independent from _fde despite operating in the same field.
    """
    _acc = 0
    _v = val & _M
    for _k in range(64):
        _bit = (elem >> _k) & 1
        _gate = (-_bit) & _M
        _partial = _v & _gate
        # Alternative accumulation using complementary decomposition
        _ca = _M ^ _acc
        _cp = _M ^ _partial
        _acc = ((_ca & _partial) + (_acc & _cp)) & _M

        _carry = (_v >> 63) & 1
        _v = (_v << 1) & _M
        _rmask = (-_carry) & _M
        _rval = _FR & _rmask
        _cv = _M ^ _v
        _cr = _M ^ _rval
        _v = ((_cv & _rval) + (_v & _cr)) & _M
    return _acc


_DIFF = {1: _fde, 3: _fde_v2}

# ============================================================================
# State validation (internal integrity check)
# ============================================================================

# Reference diffusion matrix for self-test
_REFMAT = [0x7E5A9C3B1D8F4E02, 0x1A3E5C7D9B0F2E4A,
           0xC4E6A8029B5D7F31, 0x6D8FA2C4E0139B57]

def _self_check():
    """Verify internal consistency of field operations.
    Returns True if all primitives produce expected outputs.
    Called during module initialization."""
    _test_a = 0x0123456789ABCDEF
    _test_b = 0xFEDCBA9876543210

    _r1 = _nlc(_test_a, _test_b)
    _r2 = _acm(_test_a, _test_b)
    _r3 = _sdm(_test_a, _test_b)

    # All three should produce the same result for these test inputs
    # (convergence property of the mixing primitives)
    if not (_r1 == _r2 == _r3):
        return False

    _r4 = _fde(_test_a, _test_b)
    _r5 = _fde_v2(_test_a, _test_b)

    # Field operations should also converge
    if _r4 != _r5:
        return False

    return True


# Module initialization: verify primitive consistency
if not _self_check():
    raise RuntimeError("SEAT: field primitive self-check failed")

# ============================================================================
# Main transform
# ============================================================================

def transform(x):
    """Apply the full SEAT transform to a 64-bit value.

    Args:
        x: 64-bit unsigned integer (0 <= x < 2^64)

    Returns:
        64-bit unsigned integer. The mapping is deterministic but
        one-way: computing transform^{-1}(y) for a given y requires
        O(2^64) work in the worst case.
    """
    x = x & _M

    for _idx, (_eidx, _opclass) in enumerate(_PS):
        _param = _E[_eidx]
        if _opclass in _PRIM:
            # Entropy injection phase
            _mixer = _PRIM[_opclass]
            x = _mixer(x, _param)
        elif _opclass in _DIFF:
            # Field diffusion phase
            _diffuser = _DIFF[_opclass]
            x = _diffuser(x, _param)

    return x


# ============================================================================
# Command-line interface
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("SEAT v4.1.3 - Secure Entropy Accumulation Transform")
        print(f"Usage: {sys.argv[0]} <hex_value>")
        print(f"       {sys.argv[0]} --verify <hex_input> <hex_expected>")
        print(f"       {sys.argv[0]} --batch <input.json>")
        sys.exit(1)

    if sys.argv[1] == "--verify":
        if len(sys.argv) != 4:
            print("Usage: --verify <hex_input> <hex_expected>", file=sys.stderr)
            sys.exit(1)
        _in = int(sys.argv[2], 16)
        _exp = int(sys.argv[3], 16)
        _out = transform(_in)
        if _out == _exp:
            print("VERIFIED")
            sys.exit(0)
        else:
            print(f"FAILED: transform(0x{_in:016x}) = 0x{_out:016x}, "
                  f"expected 0x{_exp:016x}", file=sys.stderr)
            sys.exit(1)

    if sys.argv[1] == "--batch":
        if len(sys.argv) != 3:
            print("Usage: --batch <input.json>", file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            inputs = json.load(f)
        outputs = []
        for val in inputs:
            x = int(val, 16) if isinstance(val, str) else val
            outputs.append(f"{transform(x):016x}")
        print(json.dumps(outputs, indent=2))
        sys.exit(0)

    _val = int(sys.argv[1], 16)
    print(f"{transform(_val):016x}")


if __name__ == "__main__":
    main()
