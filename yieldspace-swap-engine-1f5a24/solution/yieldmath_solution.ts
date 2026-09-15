
import * as M from './math64x64.js';
import * as E from './exp64x64.js';

const ONE = 0x10000000000000000n;
const WAD = 10n ** 18n;
const MAX = (1n << 128n) - 1n;

function computeA(timeTillMaturity: bigint, k: bigint, g: bigint): bigint {
  const t = M.mul(k, M.fromUInt(timeTillMaturity));
  if (t < 0n) throw new Error('t must be positive');
  const a = M.sub(ONE, M.mul(g, t));
  if (a <= 0n) throw new Error('Too far from maturity');
  if (a > ONE) throw new Error('g must be positive');
  return a;
}

export function fyTokenOutForSharesIn(
  sharesReserves: bigint, fyTokenReserves: bigint, sharesIn: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  // normalizedSharesReserves = mu * sharesReserves
  const nsr = M.mulu(mu, sharesReserves);
  if (nsr > MAX) throw new Error('Rate overflow (nsr)');

  const cDivMu = M.div(c, mu);

  // za = c/mu * (nsr^a)
  const za = M.mulu(cDivMu, E.normalizedPow(nsr, a, ONE));
  if (za > MAX) throw new Error('Rate overflow (za)');

  // ya = fyTokenReserves^a
  const ya = E.normalizedPow(fyTokenReserves, a, ONE);

  // normalizedSharesIn = mu * sharesIn
  const nsi = M.mulu(mu, sharesIn);
  if (nsi > MAX) throw new Error('Rate overflow (nsi)');

  // zx = nsr + nsi
  const zx = nsr + nsi;
  if (zx > MAX) throw new Error('Too many shares in');

  // zxa = c/mu * (zx^a)
  const zxa = M.mulu(cDivMu, E.normalizedPow(zx, a, ONE));
  if (zxa > MAX) throw new Error('Rate overflow (zxa)');

  // sum = za + ya - zxa
  const sum = za + ya - zxa;
  if (sum > za + ya) throw new Error('Sum underflow');

  // result = fyTokenReserves - sum^(1/a)
  const fyTokenOut = fyTokenReserves - E.normalizedPow(sum, ONE, a);
  if (fyTokenOut < 0n || fyTokenOut > MAX) throw new Error('Rounding error');
  if (fyTokenOut > fyTokenReserves) throw new Error('> fyToken reserves');

  return fyTokenOut;
}

export function sharesOutForFYTokenIn(
  sharesReserves: bigint, fyTokenReserves: bigint, fyTokenIn: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const nsr = M.mulu(mu, sharesReserves);
  if (nsr > MAX) throw new Error('Rate overflow (nsr)');

  const cDivMu = M.div(c, mu);

  // za = c/mu * (nsr^a)
  const za = M.mulu(cDivMu, E.normalizedPow(nsr, a, ONE));
  if (za > MAX) throw new Error('Rate overflow (za)');

  // ya = fyTokenReserves^a
  const ya = E.normalizedPow(fyTokenReserves, a, ONE);

  // yxa = (fyTokenReserves + fyTokenIn)^a
  const yxa = E.normalizedPow(fyTokenReserves + fyTokenIn, a, ONE);

  const zaYaYxa = za + ya - yxa;
  if (zaYaYxa > MAX) throw new Error('Rate overflow (yxa)');

  // rightTerm = (1/mu) * ((zaYaYxa / (c/mu))^(1/a))
  // Step 1: divu(zaYaYxa, c/mu) — divide as integers, get 64.64 result
  const divided = M.divu(zaYaYxa, cDivMu);
  // Step 2: normalizedPow(divided, ONE, a) — raise to power 1/a
  const powResult = E.normalizedPow(divided, ONE, a);
  // Step 3: div(powResult, mu) — divide by mu in 64.64
  const rightTerm = M.div(powResult, mu);

  if (rightTerm > sharesReserves) throw new Error('Rate underflow');
  return sharesReserves - rightTerm;
}

export function fyTokenInForSharesOut(
  sharesReserves: bigint, fyTokenReserves: bigint, sharesOut: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const nsr = M.mulu(mu, sharesReserves);
  if (nsr > MAX) throw new Error('Rate overflow (nsr)');

  const cDivMu = M.div(c, mu);

  // za = c/mu * (nsr^a)
  const za = M.mulu(cDivMu, E.normalizedPow(nsr, a, ONE));
  if (za > MAX) throw new Error('Rate overflow (za)');

  // ya = fyTokenReserves^a
  const ya = E.normalizedPow(fyTokenReserves, a, ONE);

  // normalizedSharesOut = mu * sharesOut
  const nso = M.mulu(mu, sharesOut);
  if (nso > MAX) throw new Error('Rate overflow (nso)');

  if (nsr < nso) throw new Error('Too many shares in');
  const zx = nsr - nso;

  // zxa = c/mu * (zx^a)
  const zxa = M.mulu(cDivMu, E.normalizedPow(zx, a, ONE));

  // sum = za + ya - zxa
  const sum = za + ya - zxa;
  if (sum > MAX) throw new Error('> fyToken reserves');

  // result = sum^(1/a) - fyTokenReserves
  const result = E.normalizedPow(sum, ONE, a) - fyTokenReserves;
  if (result < 0n || result > MAX) throw new Error('Rounding error');

  return result;
}

export function sharesInForFYTokenOut(
  sharesReserves: bigint, fyTokenReserves: bigint, fyTokenOut: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const nsr = M.mulu(mu, sharesReserves);
  if (nsr > MAX) throw new Error('Rate overflow (nsr)');

  const cDivMu = M.div(c, mu);

  // za = c/mu * (nsr^a)
  const za = M.mulu(cDivMu, E.normalizedPow(nsr, a, ONE));
  if (za > MAX) throw new Error('Rate overflow (za)');

  // ya = fyTokenReserves^a
  const ya = E.normalizedPow(fyTokenReserves, a, ONE);

  // yxa = (fyTokenReserves - fyTokenOut)^a
  if (fyTokenOut > fyTokenReserves) throw new Error('Underflow (yxa)');
  const yxa = E.normalizedPow(fyTokenReserves - fyTokenOut, a, ONE);

  const zaYaYxa = za + ya - yxa;
  if (zaYaYxa > MAX) throw new Error('Rate overflow (zyy)');

  // subtotal = (1/mu) * ((zaYaYxa / (c/mu))^(1/a))
  const divided = M.divu(zaYaYxa, cDivMu);
  const powResult = E.normalizedPow(divided, ONE, a);
  const subtotal = M.div(ONE, mu);
  const leftTerm = M.mul(subtotal, powResult);

  // sharesOut = leftTerm - sharesReserves (as uint128)
  // leftTerm is int128 (positive), interpreted as the new shares position
  // The result is how many shares must be added
  const sharesNeeded = leftTerm - sharesReserves;
  if (sharesNeeded < 0n) throw new Error('Underflow error');
  if (sharesNeeded > leftTerm) throw new Error('Underflow error');

  return sharesNeeded;
}

export function maxFYTokenIn(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const nsr = M.mulu(mu, sharesReserves);
  if (nsr > MAX) throw new Error('Rate overflow (nsr)');

  const cDivMu = M.div(c, mu);

  // za = c/mu * (nsr^a)
  const za = M.mulu(cDivMu, E.normalizedPow(nsr, a, ONE));
  if (za > MAX) throw new Error('Rate overflow (za)');

  // ya = fyTokenReserves^a
  const ya = E.normalizedPow(fyTokenReserves, a, ONE);

  // sum = za + ya (no trade subtraction for max)
  const sum = za + ya;
  if (sum > MAX) throw new Error('> fyToken reserves');

  // result = sum^(1/a) - fyTokenReserves
  const result = E.normalizedPow(sum, ONE, a) - fyTokenReserves;
  if (result < 0n || result > MAX) throw new Error('Rounding error');

  return result;
}

export function maxFYTokenOut(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const cDivMu = M.div(c, mu);

  // za = c/mu * ((mu * (sharesReserves / 1e18))^a)
  const za = M.mul(cDivMu, E.pow(M.mul(mu, M.divu(sharesReserves, WAD)), a));

  // ya = (fyTokenReserves / 1e18)^a
  const ya = E.pow(M.divu(fyTokenReserves, WAD), a);

  // numerator = za + ya
  const numerator = M.add(za, ya);

  // denominator = c/mu + 1
  const denominator = M.add(cDivMu, ONE);

  // rightTerm = (numerator / denominator)^(1/a)
  const rightTerm = E.pow(M.div(numerator, denominator), M.div(ONE, a));

  // maxFYTokenOut = fyTokenReserves - rightTerm * 1e18
  const fyTokenOut = fyTokenReserves - M.mulu(rightTerm, WAD);
  if (fyTokenOut < 0n || fyTokenOut > MAX) throw new Error('Underflow error');
  if (fyTokenOut > fyTokenReserves) throw new Error('Underflow error');

  return fyTokenOut;
}

export function maxSharesIn(
  sharesReserves: bigint, fyTokenReserves: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');
  const a = computeA(timeTillMaturity, k, g);

  const cDivMu = M.div(c, mu);

  // za = c/mu * ((mu * (sharesReserves / 1e18))^a)
  const za = M.mul(cDivMu, E.pow(M.mul(mu, M.divu(sharesReserves, WAD)), a));

  // ya = (fyTokenReserves / 1e18)^a
  const ya = E.pow(M.divu(fyTokenReserves, WAD), a);

  // numerator = za + ya
  const numerator = M.add(za, ya);

  // denominator = c/mu + 1
  const denominator = M.add(cDivMu, ONE);

  // leftTerm = (1/mu) * (numerator / denominator)^(1/a)
  const leftTerm = M.mul(M.div(ONE, mu), E.pow(M.div(numerator, denominator), M.div(ONE, a)));

  // maxSharesIn = leftTerm * 1e18 - sharesReserves
  const sharesIn = M.mulu(leftTerm, WAD) - sharesReserves;
  if (sharesIn < 0n || sharesIn > MAX) throw new Error('Underflow error');

  return sharesIn;
}

export function invariant(
  sharesReserves: bigint, fyTokenReserves: bigint, totalSupply: bigint,
  timeTillMaturity: bigint, k: bigint, g: bigint, c: bigint, mu: bigint
): bigint {
  if (totalSupply === 0n) return 0n;
  if (c <= 0n || mu <= 0n) throw new Error('c and mu must be positive');

  const a = computeA(timeTillMaturity, k, g);
  const cDivMu = M.div(c, mu);

  // za = c/mu * ((mu * (sharesReserves / 1e18))^a)
  const za = M.mul(cDivMu, E.pow(M.mul(mu, M.divu(sharesReserves, WAD)), a));

  // ya = (fyTokenReserves / 1e18)^a
  const ya = E.pow(M.divu(fyTokenReserves, WAD), a);

  // numerator = za + ya
  const numerator = M.add(za, ya);

  // denominator = c/mu + 1
  const denominator = M.add(cDivMu, ONE);

  // topTerm = c/mu * (numerator / denominator)^(1/a)
  const topTerm = M.mul(cDivMu, E.pow(M.div(numerator, denominator), M.div(ONE, a)));

  // result = topTerm * WAD * WAD / totalSupply
  const result = (M.mulu(topTerm, WAD) * WAD) / totalSupply;

  return result;
}