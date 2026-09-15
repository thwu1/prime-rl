
// YieldSpace AMM swap engine.
// Implements the constant-function market maker invariant:
//   c/mu * (mu*z)^(1-t) + y^(1-t) = k
// where z = share reserves, y = fyToken reserves,
// t = g * k * timeTillMaturity, and k is a constant.

import * as M from './math64x64.js';
import * as E from './exp64x64.js';

const ONE = 0x10000000000000000n;
const WAD = 10n ** 18n;
const MAX = (1n << 128n) - 1n;

/**
 * Compute the time-adjusted exponent for the invariant.
 */
function computeA(timeTillMaturity: bigint, k: bigint, g: bigint): bigint {
  const t = M.mul(k, M.fromUInt(timeTillMaturity));
  if (t < 0n) throw new Error('t must be positive');
  const a = M.sub(ONE, M.mul(g, t));
  if (a <= 0n) throw new Error('Too far from maturity');
  if (a > ONE) throw new Error('g must be positive');
  return a;
}

/**
 * Amount of fyToken received for a given amount of shares sold to the pool.
 * @param sharesReserves vault shares reserve (uint128, 1e18 scale)
 * @param fyTokenReserves fyToken reserves (uint128, 1e18 scale)
 * @param sharesIn shares to trade (uint128, 1e18 scale)
 * @param timeTillMaturity seconds until maturity
 * @param k time coefficient (64.64)
 * @param g fee coefficient (64.64)
 * @param c share price in base terms (64.64)
 * @param mu normalization factor (64.64)
 * @returns fyTokenOut amount (uint128)
 */
export function fyTokenOutForSharesIn(
  sharesReserves: bigint, fyTokenReserves: bigint, sharesIn: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: fyTokenOutForSharesIn');
}

/**
 * Amount of shares received for a given amount of fyToken sold to the pool.
 * @returns sharesOut amount (uint128)
 */
export function sharesOutForFYTokenIn(
  sharesReserves: bigint, fyTokenReserves: bigint, fyTokenIn: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: sharesOutForFYTokenIn');
}

/**
 * Amount of fyToken needed to buy a given amount of shares from the pool.
 * @returns fyTokenIn amount (uint128)
 */
export function fyTokenInForSharesOut(
  sharesReserves: bigint, fyTokenReserves: bigint, sharesOut: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: fyTokenInForSharesOut');
}

/**
 * Amount of shares needed to buy a given amount of fyToken from the pool.
 * @returns sharesIn amount (uint128)
 */
export function sharesInForFYTokenOut(
  sharesReserves: bigint, fyTokenReserves: bigint, fyTokenOut: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: sharesInForFYTokenOut');
}

/**
 * Maximum fyToken a user could sell to the pool.
 * @returns maxFYTokenIn (uint128)
 */
export function maxFYTokenIn(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: maxFYTokenIn');
}

/**
 * Maximum fyToken a user could buy from the pool.
 * @returns maxFYTokenOut (uint128)
 */
export function maxFYTokenOut(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: maxFYTokenOut');
}

/**
 * Maximum shares a user could sell to the pool.
 * @returns maxSharesIn (uint128)
 */
export function maxSharesIn(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: maxSharesIn');
}

/**
 * Pool invariant per LP token.
 * @param totalSupply total LP token supply (uint256)
 * @returns invariant value (uint128)
 */
export function invariant(
  sharesReserves: bigint, fyTokenReserves: bigint, totalSupply: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  // TODO: Implement
  throw new Error('Not implemented: invariant');
}
