#!/usr/bin/env python3
"""Python ctypes wrapper for libivol.so implied volatility solver."""

import ctypes
import os
import argparse

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libivol.so')
_lib = ctypes.CDLL(_lib_path)

_lib.bs_price.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                           ctypes.c_double, ctypes.c_double]
_lib.bs_price.restype = ctypes.c_double

_lib.implied_vol.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                              ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.implied_vol.restype = ctypes.c_double


def black_scholes_price(is_call, strike, forward, total_variance, discount_df):
    """Compute Black-Scholes option price via C library."""
    return _lib.bs_price(int(is_call), strike, forward, total_variance, discount_df)


def implied_volatility(is_call, price, forward, strike, tte, discount_df):
    """Compute Black-Scholes implied volatility via C library."""
    return _lib.implied_vol(int(is_call), price, forward, strike, tte, discount_df)


def main():
    parser = argparse.ArgumentParser(description="BS Implied Volatility Solver")
    parser.add_argument("--forward", type=float, required=True)
    parser.add_argument("--strike", type=float, required=True)
    parser.add_argument("--tte", type=float, required=True)
    parser.add_argument("--df", type=float, required=True)
    parser.add_argument("--price", type=float, required=True)
    parser.add_argument("--type", type=str, required=True, choices=["call", "put"])
    args = parser.parse_args()

    is_call = args.type == "call"
    iv = implied_volatility(is_call, args.price, args.forward, args.strike,
                            args.tte, args.df)
    print(f"{iv:.15e}")


if __name__ == "__main__":
    main()
