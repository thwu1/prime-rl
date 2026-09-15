
// Verification runner: imports all modules, runs golden value and property tests,
// outputs JSON results. Run with: npx tsx src/verify.ts

import { fromUInt, div, mul, sub, ONE, WAD } from './math64x64.js';
import { normalizedPow, pow } from './exp64x64.js';
import {
  fyTokenOutForSharesIn, sharesOutForFYTokenIn,
  sharesInForFYTokenOut, fyTokenInForSharesOut,
  maxFYTokenIn, maxFYTokenOut, maxSharesIn,
  invariant
} from './yieldmath.js';

// Pool parameters matching reference test suite
const invK = 25n * 365n * 24n * 60n * 60n * 10n;
const k = div(fromUInt(1n), fromUInt(invK));
const g1 = div(fromUInt(95n), fromUInt(100n));
const g2 = div(fromUInt(100n), fromUInt(95n));
const c = div(fromUInt(11n), fromUInt(10n));
const mu = div(fromUInt(105n), fromUInt(100n));
const sharesReserves = 1100000n * WAD;
const fyTokenReserves = 1500000n * WAD;
const timeTillMaturity = 90n * 24n * 60n * 60n * 10n;
const totalSupply = 1200000n * WAD;

const results: Record<string, any> = {};

function safe(fn: () => any, label: string): any {
  try {
    return fn();
  } catch (e: any) {
    results[label + '_error'] = e.message || String(e);
    return null;
  }
}

// Golden value tests for fyTokenOutForSharesIn
safe(() => {
  const inputs = [50000n, 100000n, 200000n, 500000n, 900000n];
  results.fyTokenOutForSharesIn = inputs.map(x =>
    String(fyTokenOutForSharesIn(sharesReserves, fyTokenReserves, x * WAD, timeTillMaturity, k, g1, c, mu) / WAD)
  );
}, 'fyTokenOutForSharesIn');

// Golden value tests for sharesInForFYTokenOut
safe(() => {
  const inputs = [50000n, 100000n, 200000n, 900000n];
  results.sharesInForFYTokenOut = inputs.map(x =>
    String(sharesInForFYTokenOut(sharesReserves, fyTokenReserves, x * WAD, timeTillMaturity, k, g1, c, mu) / WAD)
  );
}, 'sharesInForFYTokenOut');

// Golden value tests for sharesOutForFYTokenIn (uses g2)
safe(() => {
  const inputs = [25000n, 50000n, 100000n, 200000n, 500000n];
  results.sharesOutForFYTokenIn = inputs.map(x =>
    String(sharesOutForFYTokenIn(sharesReserves, fyTokenReserves, x * WAD, timeTillMaturity, k, g2, c, mu) / WAD)
  );
}, 'sharesOutForFYTokenIn');

// Golden value tests for fyTokenInForSharesOut (uses g2)
safe(() => {
  const inputs = [50000n, 100000n, 200000n, 300000n, 500000n, 950000n];
  results.fyTokenInForSharesOut = inputs.map(x =>
    String(fyTokenInForSharesOut(sharesReserves, fyTokenReserves, x * WAD, timeTillMaturity, k, g2, c, mu) / WAD)
  );
}, 'fyTokenInForSharesOut');

// Mirror check 1: fyTokenOutForSharesIn -> sharesInForFYTokenOut
safe(() => {
  const input = 100000n * WAD;
  const fyOut = fyTokenOutForSharesIn(sharesReserves, fyTokenReserves, input, timeTillMaturity, k, g1, c, mu);
  const sharesBack = sharesInForFYTokenOut(sharesReserves, fyTokenReserves, fyOut, timeTillMaturity, k, g1, c, mu);
  results.mirror_input = String(input / WAD);
  results.mirror_result = String(sharesBack / WAD);
}, 'mirror');

// Mirror check 2: sharesOutForFYTokenIn -> fyTokenInForSharesOut
safe(() => {
  const input = 100000n * WAD;
  const sharesOut = sharesOutForFYTokenIn(sharesReserves, fyTokenReserves, input, timeTillMaturity, k, g2, c, mu);
  const fyBack = fyTokenInForSharesOut(sharesReserves, fyTokenReserves, sharesOut, timeTillMaturity, k, g2, c, mu);
  results.mirror2_input = String(input / WAD);
  results.mirror2_result = String(fyBack / WAD);
}, 'mirror2');

// Maturity convergence: at t=0, g=1, fyTokenOut should equal c * sharesIn
safe(() => {
  const input = 100000n * WAD;
  const gOne = ONE; // g = 1.0 (no fees)
  const matResult = fyTokenOutForSharesIn(sharesReserves, fyTokenReserves, input, 0n, k, gOne, c, mu);
  results.maturity_result = String(matResult / WAD);
  results.maturity_expected = String((11n * input / 10n) / WAD);
}, 'maturity');

// Max functions
safe(() => {
  results.maxFYTokenIn = String(maxFYTokenIn(sharesReserves, fyTokenReserves, timeTillMaturity, k, g2, c, mu));
}, 'maxFYTokenIn');

safe(() => {
  results.maxFYTokenOut = String(maxFYTokenOut(sharesReserves, fyTokenReserves, timeTillMaturity, k, g1, c, mu));
}, 'maxFYTokenOut');

safe(() => {
  results.maxSharesIn = String(maxSharesIn(sharesReserves, fyTokenReserves, timeTillMaturity, k, g1, c, mu));
}, 'maxSharesIn');

// Invariant
safe(() => {
  results.invariant = String(invariant(sharesReserves, fyTokenReserves, totalSupply, timeTillMaturity, k, g2, c, mu));
}, 'invariant');

// normalizedPow identity check: normalizedPow(x, ONE, ONE) ~= x
safe(() => {
  const testVal = 1000000000000000000n; // 1e18
  const r = normalizedPow(testVal, ONE, ONE);
  results.normPow_identity = String(r);
  results.normPow_identity_expected = String(testVal);
}, 'normPow_identity');

console.log(JSON.stringify(results));
