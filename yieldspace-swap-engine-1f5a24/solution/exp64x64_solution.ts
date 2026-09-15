
import * as M from './math64x64.js';

const MAX128 = (1n << 128n) - 1n;
const ONE = 0x10000000000000000n;

/**
 * Raise 64.64 to 64.64 power: x^y = 2^(y * log_2(x))
 */
export function pow(x: bigint, y: bigint): bigint {
  return M.exp_2(M.mul(y, M.log_2(x)));
}

/**
 * Base-2 logarithm of unsigned 128-bit integer.
 * Returns result multiplied by 2^121.
 */
export function log2(x: bigint): bigint {
  if (x === 0n) throw new Error('log2: x must not be zero');

  let b = BigInt(x);
  let l = 0xFE000000000000000000000000000000n; // 127 * 2^121

  // Integer part: find position of MSB
  if (b < 0x10000000000000000n) {
    l -= 0x80000000000000000000000000000000n;
    b <<= 64n;
  }
  if (b < 0x1000000000000000000000000n) {
    l -= 0x40000000000000000000000000000000n;
    b <<= 32n;
  }
  if (b < 0x10000000000000000000000000000n) {
    l -= 0x20000000000000000000000000000000n;
    b <<= 16n;
  }
  if (b < 0x1000000000000000000000000000000n) {
    l -= 0x10000000000000000000000000000000n;
    b <<= 8n;
  }
  if (b < 0x10000000000000000000000000000000n) {
    l -= 0x8000000000000000000000000000000n;
    b <<= 4n;
  }
  if (b < 0x40000000000000000000000000000000n) {
    l -= 0x4000000000000000000000000000000n;
    b <<= 2n;
  }
  if (b < 0x80000000000000000000000000000000n) {
    l -= 0x2000000000000000000000000000000n;
    b <<= 1n;
  }

  // Fractional part: 57 squaring iterations (bits 120 down to 64)
  for (let bit = 120n; bit >= 64n; bit--) {
    b = (b * b) >> 127n;
    if (b >= 0x100000000000000000000000000000000n) {
      b >>= 1n;
      l |= (1n << bit);
    }
  }

  return l;
}

/**
 * Compute 2^(x / 2^121) for unsigned 128-bit x.
 * Uses 57 precomputed constants for 2^(1/2^k) in 128-bit precision.
 */
export function pow2(x: bigint): bigint {
  let r = 0x80000000000000000000000000000000n; // 2^127

  // 57 precomputed constants for bits 120 down to 64
  // Each constant is 2^(1/2^k) * 2^127 (128-bit fixed-point)
  const table: [bigint, bigint][] = [
    [1n << 120n, 0xb504f333f9de6484597d89b3754abe9fn],
    [1n << 119n, 0x9837f0518db8a96f46ad23182e42f6f6n],
    [1n << 118n, 0x8b95c1e3ea8bd6e6fbe4628758a53c90n],
    [1n << 117n, 0x85aac367cc487b14c5c95b8c2154c1b2n],
    [1n << 116n, 0x82cd8698ac2ba1d73e2a475b46520bffn],
    [1n << 115n, 0x8164d1f3bc0307737be56527bd14def4n],
    [1n << 114n, 0x80b1ed4fd999ab6c25335719b6e6fd20n],
    [1n << 113n, 0x8058d7d2d5e5f6b094d589f608ee4aa2n],
    [1n << 112n, 0x802c6436d0e04f50ff8ce94a6797b3cen],
    [1n << 111n, 0x8016302f174676283690dfe44d11d008n],
    [1n << 110n, 0x800b179c82028fd0945e54e2ae18f2f0n],
    [1n << 109n, 0x80058baf7fee3b5d1c718b38e549cb93n],
    [1n << 108n, 0x8002c5d00fdcfcb6b6566a58c048be1fn],
    [1n << 107n, 0x800162e61bed4a48e84c2e1a463473d9n],
    [1n << 106n, 0x8000b17292f702a3aa22beacca949013n],
    [1n << 105n, 0x800058b92abbae02030c5fa5256f41fen],
    [1n << 104n, 0x80002c5c8dade4d71776c0f4dbea67d6n],
    [1n << 103n, 0x8000162e44eaf636526be456600bdbe4n],
    [1n << 102n, 0x80000b1721fa7c188307016c1cd4e8b6n],
    [1n << 101n, 0x8000058b90de7e4cecfc487503488bb1n],
    [1n << 100n, 0x800002c5c8678f36cbfce50a6de60b14n],
    [1n << 99n,  0x80000162e431db9f80b2347b5d62e516n],
    [1n << 98n,  0x800000b1721872d0c7b08cf1e0114152n],
    [1n << 97n,  0x80000058b90c1aa8a5c3736cb77e8dffn],
    [1n << 96n,  0x8000002c5c8605a4635f2efc2362d978n],
    [1n << 95n,  0x800000162e4300e635cf4a109e3939bdn],
    [1n << 94n,  0x8000000b17217ff81bef9c551590cf83n],
    [1n << 93n,  0x800000058b90bfdd4e39cd52c0cfa27cn],
    [1n << 92n,  0x80000002c5c85fe6f72d669e0e76e411n],
    [1n << 91n,  0x8000000162e42ff18f9ad35186d0df28n],
    [1n << 90n,  0x80000000b17217f84cce71aa0dcfffe7n],
    [1n << 89n,  0x8000000058b90bfc07a77ad56ed22aaan],
    [1n << 88n,  0x800000002c5c85fdfc23cdead40da8d6n],
    [1n << 87n,  0x80000000162e42fefc25eb1571853a66n],
    [1n << 86n,  0x800000000b17217f7d97f692baacded5n],
    [1n << 85n,  0x80000000058b90bfbead3b8b5dd254d7n],
    [1n << 84n,  0x8000000002c5c85fdf4eedd62f084e67n],
    [1n << 83n,  0x800000000162e42fefa58aef378bf586n],
    [1n << 82n,  0x8000000000b17217f7d24a78a3c7ef02n],
    [1n << 81n,  0x800000000058b90bfbe9067c93e474a6n],
    [1n << 80n,  0x80000000002c5c85fdf47b8e5a72599fn],
    [1n << 79n,  0x8000000000162e42fefa3bdb315934a2n],
    [1n << 78n,  0x80000000000b17217f7d1d7299b49c46n],
    [1n << 77n,  0x8000000000058b90bfbe8e9a8d1c4ea0n],
    [1n << 76n,  0x800000000002c5c85fdf4745969ea76fn],
    [1n << 75n,  0x80000000000162e42fefa3a0df5373bfn],
    [1n << 74n,  0x800000000000b17217f7d1cff4aac1e1n],
    [1n << 73n,  0x80000000000058b90bfbe8e7db95a2f1n],
    [1n << 72n,  0x8000000000002c5c85fdf473e61ae1f8n],
    [1n << 71n,  0x800000000000162e42fefa39f121751cn],
    [1n << 70n,  0x8000000000000b17217f7d1cf815bb96n],
    [1n << 69n,  0x800000000000058b90bfbe8e7bec1e0dn],
    [1n << 68n,  0x80000000000002c5c85fdf473dee5f17n],
    [1n << 67n,  0x8000000000000162e42fefa39ef5438fn],
    [1n << 66n,  0x80000000000000b17217f7d1cf7a26c8n],
    [1n << 65n,  0x8000000000000058b90bfbe8e7bcf4a4n],
    [1n << 64n,  0x800000000000002c5c85fdf473de72a2n],
  ];

  for (const [mask, constant] of table) {
    if ((x & mask) > 0n) {
      r = (r * constant) >> 127n;
    }
  }

  // Adjust for integer part of exponent
  r >>= 127n - (x >> 121n);

  return r;
}

/**
 * Normalized fractional power: x^(y/z) * 2^(128*(1-y/z))
 */
export function normalizedPow(x: bigint, y: bigint, z: bigint): bigint {
  if (z === 0n) throw new Error('normalizedPow: z must not be zero');

  if (x === 0n) {
    if (y === 0n) throw new Error('normalizedPow: 0^0 undefined');
    return 0n;
  }

  const l = (MAX128 - log2(x)) * y / z;
  if (l > MAX128) return 0n;

  return pow2(MAX128 - l);
}