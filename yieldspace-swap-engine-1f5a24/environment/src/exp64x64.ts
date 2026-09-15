
// Fractional exponentiation for unsigned 128-bit integers.
// This module provides normalized power functions used by the AMM swap engine.

import * as M from './math64x64.js';

const MAX128 = (1n << 128n) - 1n;
const ONE = 0x10000000000000000n;

/**
 * Raise a 64.64 number to a 64.64 power: x^y = 2^(y * log_2(x))
 * Both x and y are signed 64.64 fixed-point numbers.
 */
export function pow(x: bigint, y: bigint): bigint {
  return M.exp_2(M.mul(y, M.log_2(x)));
}

/**
 * Base-2 logarithm of an unsigned 128-bit integer.
 * @param x unsigned 128-bit integer (must be > 0)
 * @returns log_2(x) scaled by 2^121
 *
 * TODO: Implement this function.
 */
export function log2(x: bigint): bigint {
  throw new Error('Not implemented: log2 for uint128');
}

/**
 * Compute 2 raised to a power given as unsigned 128-bit integer
 * scaled by 2^121.
 * @param x the exponent, multiplied by 2^121
 * @returns 2^(x / 2^121) as unsigned 128-bit integer
 *
 * TODO: Implement this function.
 */
export function pow2(x: bigint): bigint {
  throw new Error('Not implemented: pow2 for uint128');
}

/**
 * Normalized fractional power: x^(y/z) * 2^(128 * (1 - y/z))
 * @param x base (unsigned 128-bit integer)
 * @param y numerator of exponent (unsigned 128-bit)
 * @param z denominator of exponent (unsigned 128-bit)
 * @returns x^(y/z) with normalization factor to keep result in uint128 range
 *
 * The identity normalizedPow(x, ONE, ONE) ~= x should hold.
 *
 * TODO: Implement this function.
 */
export function normalizedPow(x: bigint, y: bigint, z: bigint): bigint {
  throw new Error('Not implemented: normalizedPow');
}
