
// Signed 64.64 fixed-point arithmetic library for BigInt.
// A 64.64 number is stored as a bigint whose real value = raw / 2^64.

export const ONE = 0x10000000000000000n; // 1.0 in 64.64
export const WAD = 10n ** 18n;
export const MAX = (1n << 128n) - 1n; // max uint128
const MIN_64x64 = -(1n << 127n);
const MAX_64x64 = (1n << 127n) - 1n;

/** Convert unsigned integer to 64.64 */
export function fromUInt(x: bigint): bigint {
  if (x > 0x7FFFFFFFFFFFFFFFn) throw new Error('fromUInt: overflow');
  return x << 64n;
}

/** Convert 64.64 to unsigned integer (truncate) */
export function toUInt(x: bigint): bigint {
  if (x < 0n) throw new Error('toUInt: negative');
  return x >> 64n;
}

/** 64.64 addition */
export function add(x: bigint, y: bigint): bigint {
  const r = x + y;
  if (r < MIN_64x64 || r > MAX_64x64) throw new Error('add: overflow');
  return r;
}

/** 64.64 subtraction */
export function sub(x: bigint, y: bigint): bigint {
  const r = x - y;
  if (r < MIN_64x64 || r > MAX_64x64) throw new Error('sub: overflow');
  return r;
}

/** 64.64 multiplication: (x * y) >> 64 */
export function mul(x: bigint, y: bigint): bigint {
  const r = (x * y) >> 64n;
  if (r < MIN_64x64 || r > MAX_64x64) throw new Error('mul: overflow');
  return r;
}

/** Multiply 64.64 by unsigned integer: (x * y) >> 64 */
export function mulu(x: bigint, y: bigint): bigint {
  if (y === 0n) return 0n;
  if (x < 0n) throw new Error('mulu: x must be non-negative');
  return (x * y) >> 64n;
}

/** 64.64 division: (x << 64) / y */
export function div(x: bigint, y: bigint): bigint {
  if (y === 0n) throw new Error('div: division by zero');
  const r = (x << 64n) / y;
  if (r < MIN_64x64 || r > MAX_64x64) throw new Error('div: overflow');
  return r;
}

/** Divide unsigned by unsigned, return 64.64: (x << 64) / y */
export function divu(x: bigint, y: bigint): bigint {
  if (y === 0n) throw new Error('divu: division by zero');
  const r = (x << 64n) / y;
  if (r > MAX_64x64) throw new Error('divu: overflow');
  return r;
}

/** Binary logarithm of 64.64 number, returns 64.64 */
export function log_2(x: bigint): bigint {
  if (x <= 0n) throw new Error('log_2: x must be positive');

  let msb = 0n;
  let xc = x;
  if (xc >= 0x10000000000000000n) { xc >>= 64n; msb += 64n; }
  if (xc >= 0x100000000n) { xc >>= 32n; msb += 32n; }
  if (xc >= 0x10000n) { xc >>= 16n; msb += 16n; }
  if (xc >= 0x100n) { xc >>= 8n; msb += 8n; }
  if (xc >= 0x10n) { xc >>= 4n; msb += 4n; }
  if (xc >= 0x4n) { xc >>= 2n; msb += 2n; }
  if (xc >= 0x2n) msb += 1n;

  let result = (msb - 64n) << 64n;
  let ux = x << (127n - msb);

  for (let bit = 0x8000000000000000n; bit > 0n; bit >>= 1n) {
    ux = ux * ux;
    const b = ux >> 255n;
    ux >>= 127n + b;
    result += bit * b;
  }

  return result;
}

/** Binary exponent of 64.64 number, returns 64.64: 2^x */
export function exp_2(x: bigint): bigint {
  if (x >= 0x400000000000000000n) throw new Error('exp_2: overflow');
  if (x < -0x400000000000000000n) return 0n;

  let result = 0x80000000000000000000000000000000n;

  // 64 precomputed constants for 2^(1/2^k), k=1..64, each as 129-bit fixed-point
  const table: [bigint, bigint][] = [
    [0x8000000000000000n, 0x16A09E667F3BCC908B2FB1366EA957D3En],
    [0x4000000000000000n, 0x1306FE0A31B7152DE8D5A46305C85EDECn],
    [0x2000000000000000n, 0x1172B83C7D517ADCDF7C8C50EB14A791Fn],
    [0x1000000000000000n, 0x10B5586CF9890F6298B92B71842A98363n],
    [0x800000000000000n, 0x1059B0D31585743AE7C548EB68CA417FDn],
    [0x400000000000000n, 0x102C9A3E778060EE6F7CACA4F7A29BDE8n],
    [0x200000000000000n, 0x10163DA9FB33356D84A66AE336DCDFA3Fn],
    [0x100000000000000n, 0x100B1AFA5ABCBED6129AB13EC11DC9543n],
    [0x80000000000000n, 0x10058C86DA1C09EA1FF19D294CF2F679Bn],
    [0x40000000000000n, 0x1002C605E2E8CEC506D21BFC89A23A00Fn],
    [0x20000000000000n, 0x100162F3904051FA128BCA9C55C31E5DFn],
    [0x10000000000000n, 0x1000B175EFFDC76BA38E31671CA939725n],
    [0x8000000000000n, 0x100058BA01FB9F96D6CACD4B180917C3Dn],
    [0x4000000000000n, 0x10002C5CC37DA9491D0985C348C68E7B3n],
    [0x2000000000000n, 0x1000162E525EE054754457D5995292026n],
    [0x1000000000000n, 0x10000B17255775C040618BF4A4ADE83FCn],
    [0x800000000000n, 0x1000058B91B5BC9AE2EED81E9B7D4CFABn],
    [0x400000000000n, 0x100002C5C89D5EC6CA4D7C8ACC017B7C9n],
    [0x200000000000n, 0x10000162E43F4F831060E02D839A9D16Dn],
    [0x100000000000n, 0x100000B1721BCFC99D9F890EA06911763n],
    [0x80000000000n, 0x10000058B90CF1E6D97F9CA14DBCC1628n],
    [0x40000000000n, 0x1000002C5C863B73F016468F6BAC5CA2Bn],
    [0x20000000000n, 0x100000162E430E5A18F6119E3C02282A5n],
    [0x10000000000n, 0x1000000B1721835514B86E6D96EFD1BFEn],
    [0x8000000000n, 0x100000058B90C0B48C6BE5DF846C5B2EFn],
    [0x4000000000n, 0x10000002C5C8601CC6B9E94213C72737An],
    [0x2000000000n, 0x1000000162E42FFF037DF38AA2B219F06n],
    [0x1000000000n, 0x10000000B17217FBA9C739AA5819F44F9n],
    [0x800000000n, 0x1000000058B90BFCDEE5ACD3C1CEDC823n],
    [0x400000000n, 0x100000002C5C85FE31F35A6A30DA1BE50n],
    [0x200000000n, 0x10000000162E42FF0999CE3541B9FFFCFn],
    [0x100000000n, 0x100000000B17217F80F4EF5AADDA45554n],
    [0x80000000n, 0x10000000058B90BFBF8479BD5A81B51ADn],
    [0x40000000n, 0x1000000002C5C85FDF84BD62AE30A74CCn],
    [0x20000000n, 0x100000000162E42FEFB2FED257559BDAAn],
    [0x10000000n, 0x1000000000B17217F7D5A7716BBA4A9AEn],
    [0x8000000n, 0x100000000058B90BFBE9DDBAC5E109CCEn],
    [0x4000000n, 0x10000000002C5C85FDF4B15DE6F17EB0Dn],
    [0x2000000n, 0x1000000000162E42FEFA494F1478FDE05n],
    [0x1000000n, 0x10000000000B17217F7D20CF927C8E94Cn],
    [0x800000n, 0x1000000000058B90BFBE8F71CB4E4B33Dn],
    [0x400000n, 0x100000000002C5C85FDF477B662B26945n],
    [0x200000n, 0x10000000000162E42FEFA3AE53369388Cn],
    [0x100000n, 0x100000000000B17217F7D1D351A389D40n],
    [0x80000n, 0x10000000000058B90BFBE8E8B2D3D4EDEn],
    [0x40000n, 0x1000000000002C5C85FDF4741BEA6E77En],
    [0x20000n, 0x100000000000162E42FEFA39FE95583C2n],
    [0x10000n, 0x1000000000000B17217F7D1CFB72B45E1n],
    [0x8000n, 0x100000000000058B90BFBE8E7CC35C3F0n],
    [0x4000n, 0x10000000000002C5C85FDF473E242EA38n],
    [0x2000n, 0x1000000000000162E42FEFA39F02B772Cn],
    [0x1000n, 0x10000000000000B17217F7D1CF7D83C1An],
    [0x800n, 0x1000000000000058B90BFBE8E7BDCBE2En],
    [0x400n, 0x100000000000002C5C85FDF473DEA871Fn],
    [0x200n, 0x10000000000000162E42FEFA39EF44D91n],
    [0x100n, 0x100000000000000B17217F7D1CF79E949n],
    [0x80n, 0x10000000000000058B90BFBE8E7BCE544n],
    [0x40n, 0x1000000000000002C5C85FDF473DE6ECAn],
    [0x20n, 0x100000000000000162E42FEFA39EF366Fn],
    [0x10n, 0x1000000000000000B17217F7D1CF79AFAn],
    [0x8n, 0x100000000000000058B90BFBE8E7BCD6Dn],
    [0x4n, 0x10000000000000002C5C85FDF473DE6B2n],
    [0x2n, 0x1000000000000000162E42FEFA39EF358n],
    [0x1n, 0x10000000000000000B17217F7D1CF79ABn],
  ];

  for (const [mask, constant] of table) {
    if ((x & mask) > 0n) {
      result = (result * constant) >> 128n;
    }
  }

  result >>= 62n - (x >> 64n);
  if (result > MAX_64x64) throw new Error('exp_2: result overflow');
  return result;
}