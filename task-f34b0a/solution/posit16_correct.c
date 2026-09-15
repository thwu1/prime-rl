/*
 * posit16_correct.c — Complete, correct posit16 arithmetic library
 *
 */

#include "posit16.h"
#include <math.h>
#include <stdlib.h>

/* =====================================================================
 * Internal helpers
 * ===================================================================== */

static inline bool _signP16(uint16_t ui) {
    return (ui >> 15) != 0;
}

static inline bool _regSignP16(uint16_t ui) {
    return ((ui >> 14) & 1) != 0;
}

static inline uint16_t _packToP16(uint16_t regime, uint16_t regA,
                                   uint16_t expA, uint16_t fracA) {
    if (regA >= 14) return regime;
    return (uint16_t)(regime + (expA << (13 - regA)) + fracA);
}

/* =====================================================================
 * Conversion: posit16 -> double
 * ===================================================================== */
double p16_to_f64(posit16_t a) {
    uint16_t uiA = a.v;

    if (uiA == 0)      return 0.0;
    if (uiA == 0x7FFF)  return 268435456.0;
    if (uiA == 0x8001)  return -268435456.0;
    if (uiA == 0x8000)  return NAN;

    bool sign = _signP16(uiA);
    if (sign) uiA = (-uiA) & 0xFFFF;

    bool regS = _regSignP16(uiA);
    uint16_t tmp = (uiA << 2) & 0xFFFF;
    int16_t k = 0;
    uint16_t shift = 2, reg;

    if (regS) {
        while (tmp >> 15) { k++; shift++; tmp = (tmp << 1) & 0xFFFF; }
        reg = k + 1;
    } else {
        k = -1;
        while (!(tmp >> 15)) { k--; shift++; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
        reg = -k;
    }

    int8_t exp = tmp >> 14;
    uint16_t frac = (tmp & 0x3FFF) >> shift;
    double fraction_max = pow(2.0, 13 - reg);
    double result = pow(4.0, k) * pow(2.0, exp) *
                    (1.0 + (double)frac / fraction_max);

    return sign ? -result : result;
}

/* =====================================================================
 * Addition: same-sign magnitude helper
 * ===================================================================== */
static posit16_t _addMagsP16(uint16_t uiA, uint16_t uiB) {
    uint16_t regA;
    uint32_t frac32A, frac32B;
    uint16_t fracA = 0, regime, tmp;
    bool sign, regSA, regSB, rcarry = 0, bitNPlusOne = 0, bitsMore = 0;
    int8_t kA = 0, expA;
    int16_t shiftRight;

    sign = _signP16(uiA);
    if (sign) { uiA = (-uiA) & 0xFFFF; uiB = (-uiB) & 0xFFFF; }

    if ((int16_t)uiA < (int16_t)uiB) {
        uint16_t t = uiA; uiA = uiB; uiB = t;
    }

    regSA = _regSignP16(uiA);
    regSB = _regSignP16(uiB);

    tmp = (uiA << 2) & 0xFFFF;
    if (regSA) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA = -1;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA = tmp >> 14;
    frac32A = ((uint32_t)(0x4000 | tmp)) << 16;
    shiftRight = kA;

    tmp = (uiB << 2) & 0xFFFF;
    if (regSB) {
        while (tmp >> 15) { shiftRight--; tmp = (tmp << 1) & 0xFFFF; }
        frac32B = ((uint32_t)(0x4000 | tmp)) << 16;
    } else {
        shiftRight++;
        while (!(tmp >> 15)) { shiftRight++; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
        frac32B = (((uint32_t)(0x4000 | tmp)) << 16) & 0x7FFFFFFF;
    }

    shiftRight = (shiftRight << 1) + expA - (tmp >> 14);

    if (shiftRight == 0) {
        frac32A += frac32B;
        if (expA) kA++;
        expA ^= 1;
        frac32A >>= 1;
    } else {
        (shiftRight > 31) ? (frac32B = 0) : (frac32B >>= shiftRight);
        frac32A += frac32B;
        rcarry = 0x80000000 & frac32A;
        if (rcarry) { if (expA) kA++; expA ^= 1; frac32A >>= 1; }
    }

    uint16_t uZ;
    if (kA < 0) { regA = (-kA) & 0xFFFF; regime = 0x4000 >> regA; }
    else        { regA = kA + 1; regime = 0x7FFF - (0x7FFF >> regA); }

    if (regA > 14) {
        uZ = (kA >= 0) ? 0x7FFF : 0x1;
    } else {
        frac32A = (frac32A & 0x3FFFFFFF) >> (regA + 1);
        fracA = frac32A >> 16;
        if (regA != 14) bitNPlusOne = (frac32A >> 15) & 0x1;
        else if (frac32A > 0) { fracA = 0; bitsMore = 1; }
        if (regA == 14 && expA) bitNPlusOne = 1;
        uZ = _packToP16(regime, regA, expA, fracA);
        if (bitNPlusOne) {
            if (frac32A & 0x7FFF) bitsMore = 1;
            uZ += (uZ & 1) | bitsMore;
        }
    }

    if (sign) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}

/* =====================================================================
 * Subtraction: different-sign magnitude helper
 * ===================================================================== */
static posit16_t _subMagsP16(uint16_t uiA, uint16_t uiB) {
    uint16_t regA;
    uint32_t frac32A, frac32B;
    uint16_t fracA = 0, regime, tmp;
    bool sign = 0, regSA, regSB, bitNPlusOne = 0, bitsMore = 0;
    int16_t shiftRight;
    int8_t kA = 0, expA;
    bool ecarry;

    sign = _signP16(uiA);
    if (sign) { uiA = (-uiA) & 0xFFFF; } else { uiB = (-uiB) & 0xFFFF; }

    if (uiA == uiB) return (posit16_t){0};
    if (uiA < uiB) { uint16_t t = uiA; uiA = uiB; uiB = t; sign = !sign; }

    regSA = _regSignP16(uiA);
    regSB = _regSignP16(uiB);

    tmp = (uiA << 2) & 0xFFFF;
    if (regSA) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA = -1;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA = tmp >> 14;
    frac32A = ((uint32_t)(0x4000 | tmp)) << 16;
    shiftRight = kA;

    tmp = (uiB << 2) & 0xFFFF;
    if (regSB) {
        while (tmp >> 15) { shiftRight--; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        shiftRight++;
        while (!(tmp >> 15)) { shiftRight++; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    frac32B = ((uint32_t)(0x4000 | tmp)) << 16;

    shiftRight = (shiftRight << 1) + expA - (tmp >> 14);

    if (shiftRight != 0) {
        if (shiftRight >= 29) {
            uint16_t uZ = uiA;
            if (sign) uZ = (-uZ) & 0xFFFF;
            return (posit16_t){uZ};
        }
        frac32B >>= shiftRight;
    }

    frac32A -= frac32B;

    while ((frac32A >> 29) == 0) { kA--; frac32A <<= 2; }
    ecarry = (0x40000000 & frac32A) >> 30;
    if (!ecarry) { if (expA == 0) kA--; expA ^= 1; frac32A <<= 1; }

    uint16_t uZ;
    if (kA < 0) { regA = (-kA) & 0xFFFF; regime = 0x4000 >> regA; }
    else        { regA = kA + 1; regime = 0x7FFF - (0x7FFF >> regA); }

    if (regA > 14) {
        uZ = (kA >= 0) ? 0x7FFF : 0x1;
    } else {
        frac32A = (frac32A & 0x3FFFFFFF) >> (regA + 1);
        fracA = frac32A >> 16;
        if (regA != 14) bitNPlusOne = (frac32A >> 15) & 0x1;
        else if (frac32A > 0) { fracA = 0; bitsMore = 1; }
        if (regA == 14 && expA) bitNPlusOne = 1;
        uZ = _packToP16(regime, regA, expA, fracA);
        if (bitNPlusOne) {
            if (frac32A & 0x7FFF) bitsMore = 1;
            uZ += (uZ & 1) | bitsMore;
        }
    }

    if (sign) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}

/* =====================================================================
 * p16_add
 * ===================================================================== */
posit16_t p16_add(posit16_t a, posit16_t b) {
    uint16_t uiA = a.v, uiB = b.v;
    if (uiA == 0 || uiB == 0) return (posit16_t){(uint16_t)(uiA | uiB)};
    if (uiA == 0x8000 || uiB == 0x8000) return P16_NAR;

    if ((uiA ^ uiB) >> 15)
        return _subMagsP16(uiA, uiB);
    else
        return _addMagsP16(uiA, uiB);
}

/* =====================================================================
 * p16_sub
 * ===================================================================== */
posit16_t p16_sub(posit16_t a, posit16_t b) {
    uint16_t uiA = a.v, uiB = b.v;
    if (uiA == 0x8000 || uiB == 0x8000) return P16_NAR;
    if (uiA == 0 || uiB == 0)
        return (posit16_t){(uint16_t)(uiA | ((-uiB) & 0xFFFF))};

    if ((uiA ^ uiB) >> 15)
        return _addMagsP16(uiA, ((-uiB) & 0xFFFF));
    else
        return _subMagsP16(uiA, ((-uiB) & 0xFFFF));
}

/* =====================================================================
 * p16_mul  [FIXED — correct round-to-nearest-even]
 * ===================================================================== */
posit16_t p16_mul(posit16_t a, posit16_t b) {
    uint16_t uiA = a.v, uiB = b.v;
    uint16_t regA, fracA, regime, tmp;
    bool signA, signB, signZ, regSA, regSB;
    bool bitNPlusOne = 0, bitsMore = 0, rcarry;
    int8_t expA, kA = 0;
    uint32_t frac32Z;

    if (uiA == 0x8000 || uiB == 0x8000) return P16_NAR;
    if (uiA == 0 || uiB == 0) return P16_ZERO;

    signA = _signP16(uiA);
    signB = _signP16(uiB);
    signZ = signA ^ signB;

    if (signA) uiA = (-uiA) & 0xFFFF;
    if (signB) uiB = (-uiB) & 0xFFFF;

    regSA = _regSignP16(uiA);
    regSB = _regSignP16(uiB);

    tmp = (uiA << 2) & 0xFFFF;
    if (regSA) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA = -1;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA = tmp >> 14;
    fracA = 0x4000 | tmp;

    tmp = (uiB << 2) & 0xFFFF;
    if (regSB) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA--;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA += tmp >> 14;
    frac32Z = (uint32_t)fracA * (0x4000 | tmp);

    if (expA > 1) { kA++; expA ^= 0x2; }

    rcarry = frac32Z >> 29;
    if (rcarry) { if (expA) kA++; expA ^= 1; frac32Z >>= 1; }

    uint16_t uZ;
    if (kA < 0) { regA = (-kA) & 0xFFFF; regime = 0x4000 >> regA; }
    else        { regA = kA + 1; regime = 0x7FFF - (0x7FFF >> regA); }

    if (regA > 14) {
        uZ = (kA >= 0) ? 0x7FFF : 0x1;
    } else {
        frac32Z = (frac32Z & 0xFFFFFFF) >> (regA - 1);
        fracA = (uint16_t)(frac32Z >> 16);
        if (regA != 14) bitNPlusOne |= (0x8000 & frac32Z);
        else if (fracA > 0) { fracA = 0; bitsMore = 1; }
        if (regA == 14 && expA) bitNPlusOne = 1;

        uZ = _packToP16(regime, regA, expA, fracA);

        if (bitNPlusOne) {
            if (0x7FFF & frac32Z) bitsMore = 1;
            uZ += (uZ & 1) | bitsMore;
        }
    }

    if (signZ) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}

/* =====================================================================
 * p16_div  [IMPLEMENTED]
 * ===================================================================== */
posit16_t p16_div(posit16_t a, posit16_t b) {
    uint16_t uiA = a.v, uiB = b.v;
    uint16_t fracA, fracB, regA, regime, tmp;
    bool signA, signB, signZ, regSA, regSB;
    bool bitNPlusOne = 0, bitsMore = 0, rcarry;
    int8_t expA, kA = 0;
    uint32_t frac32A, frac32Z, rem;

    if (uiA == 0x8000 || uiB == 0x8000 || uiB == 0) return P16_NAR;
    if (uiA == 0) return P16_ZERO;

    signA = _signP16(uiA);
    signB = _signP16(uiB);
    signZ = signA ^ signB;
    if (signA) uiA = (-uiA) & 0xFFFF;
    if (signB) uiB = (-uiB) & 0xFFFF;

    regSA = _regSignP16(uiA);
    regSB = _regSignP16(uiB);

    /* Decode A */
    tmp = (uiA << 2) & 0xFFFF;
    if (regSA) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA = -1;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA = tmp >> 14;
    fracA = 0x4000 | tmp;
    frac32A = (uint32_t)fracA << 14;

    /* Decode B */
    tmp = (uiB << 2) & 0xFFFF;
    if (regSB) {
        while (tmp >> 15) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        fracB = 0x4000 | tmp;
    } else {
        kA++;
        while (!(tmp >> 15)) { kA++; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
        fracB = 0x4000 | (tmp & 0x7FFF);
    }
    expA -= tmp >> 14;

    /* Integer division */
    div_t divresult = div((int)frac32A, (int)fracB);
    frac32Z = divresult.quot;
    rem = divresult.rem;

    if (expA < 0) { expA = 1; kA--; }

    if (frac32Z != 0) {
        rcarry = frac32Z >> 14;
        if (!rcarry) {
            if (expA == 0) kA--;
            expA ^= 1;
            frac32Z <<= 1;
        }
    }

    uint16_t uZ;
    if (kA < 0) { regA = (-kA) & 0xFFFF; regime = 0x4000 >> regA; }
    else        { regA = kA + 1; regime = 0x7FFF - (0x7FFF >> regA); }

    if (regA > 14) {
        uZ = (kA >= 0) ? 0x7FFF : 0x1;
    } else {
        frac32Z &= 0x3FFF;
        fracA = (uint16_t)(frac32Z >> (regA + 1));
        if (regA != 14) bitNPlusOne = (frac32Z >> regA) & 0x1;
        else if (fracA > 0) { fracA = 0; bitsMore = 1; }
        if (regA == 14 && expA) bitNPlusOne = 1;

        uZ = _packToP16(regime, regA, expA, fracA);

        if (bitNPlusOne) {
            if (((1u << regA) - 1) & frac32Z) bitsMore = 1;
            if (rem) bitsMore = 1;
            uZ += (uZ & 1) | bitsMore;
        }
    }

    if (signZ) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}

/* =====================================================================
 * Quire operations  [IMPLEMENTED]
 * ===================================================================== */

quire16_t q16_clr(void) {
    quire16_t q;
    q.v[0] = 0;
    q.v[1] = 0;
    return q;
}

quire16_t q16_fdp_add(quire16_t q, posit16_t a, posit16_t b) {
    uint16_t uiA = a.v, uiB = b.v;

    /* NaR check */
    if ((q.v[0] == 0x8000000000000000ULL && q.v[1] == 0) ||
        uiA == 0x8000 || uiB == 0x8000) {
        return (quire16_t){{0x8000000000000000ULL, 0}};
    }
    if (uiA == 0 || uiB == 0) return q;

    bool signA = _signP16(uiA), signB = _signP16(uiB);
    bool signZ2 = signA ^ signB;
    if (signA) uiA = (-uiA) & 0xFFFF;
    if (signB) uiB = (-uiB) & 0xFFFF;

    bool regSA = _regSignP16(uiA), regSB = _regSignP16(uiB);
    int16_t kA = 0;
    int8_t expA;
    uint16_t fracA, tmp;

    /* Decode A */
    tmp = (uiA << 2) & 0xFFFF;
    if (regSA) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA = -1;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA = tmp >> 14;
    fracA = 0x4000 | tmp;

    /* Decode B */
    tmp = (uiB << 2) & 0xFFFF;
    if (regSB) {
        while (tmp >> 15) { kA++; tmp = (tmp << 1) & 0xFFFF; }
    } else {
        kA--;
        while (!(tmp >> 15)) { kA--; tmp = (tmp << 1) & 0xFFFF; }
        tmp &= 0x7FFF;
    }
    expA += tmp >> 14;
    uint32_t frac32Z = (uint32_t)fracA * (0x4000 | tmp);

    if (expA > 1) { kA++; expA ^= 0x2; }

    bool rcarry = frac32Z >> 29;
    if (rcarry) { if (expA) kA++; expA ^= 1; frac32Z >>= 1; }

    /* Position product in 128-bit quire.
     * Dot is between bit 71 and 72 (bit 0 = MSB of v[0]).
     * firstPos = 71 - (2*kA + expA) */
    int firstPos = 71 - (kA << 1) - expA;

    quire16_t uZ2 = {{0, 0}};
    int16_t shiftRight;

    if (firstPos > 63) {
        shiftRight = firstPos - 99;
        if (shiftRight < 0)
            uZ2.v[1] = (uint64_t)frac32Z << (-shiftRight);
        else
            uZ2.v[1] = (uint64_t)frac32Z >> shiftRight;
    } else {
        shiftRight = firstPos - 35;
        if (shiftRight < 0) {
            uZ2.v[0] = (uint64_t)frac32Z << (-shiftRight);
        } else {
            uZ2.v[0] = (uint64_t)frac32Z >> shiftRight;
            uZ2.v[1] = (uint64_t)frac32Z << (64 - shiftRight);
        }
    }

    /* Negate product if sign is negative */
    if (signZ2) {
        if (uZ2.v[1] > 0) {
            uZ2.v[1] = -uZ2.v[1];
            uZ2.v[0] = ~uZ2.v[0];
        } else {
            uZ2.v[0] = -uZ2.v[0];
        }
    }

    /* 128-bit addition: result = q + uZ2 */
    quire16_t uZ;
    uZ.v[1] = q.v[1] + uZ2.v[1];
    uint64_t carry = (uZ.v[1] < q.v[1]) ? 1 : 0;
    uZ.v[0] = q.v[0] + uZ2.v[0] + carry;

    /* Prevent accidental NaR */
    if (uZ.v[0] == 0x8000000000000000ULL && uZ.v[1] == 0)
        uZ.v[0] = 0;

    return uZ;
}

posit16_t q16_to_p16(quire16_t qA) {
    /* Zero */
    if (qA.v[0] == 0 && qA.v[1] == 0)
        return P16_ZERO;
    /* NaR */
    if (qA.v[0] == 0x8000000000000000ULL && qA.v[1] == 0)
        return P16_NAR;

    bool sign = qA.v[0] >> 63;
    uint64_t hi = qA.v[0], lo = qA.v[1];

    if (sign) {
        if (lo == 0) { hi = -hi; }
        else { lo = -lo; hi = ~hi; }
    }

    int noLZ = 0;
    uint64_t frac64A;
    bool bitsMore = 0;

    if (hi == 0) {
        noLZ += 64;
        uint64_t tmp = lo;
        while (!(tmp >> 63)) { noLZ++; tmp <<= 1; }
        frac64A = tmp;
    } else {
        uint64_t tmp = hi;
        int noLZtmp = 0;
        while (!(tmp >> 63)) { noLZtmp++; tmp <<= 1; }
        noLZ += noLZtmp;
        frac64A = tmp;
        if (noLZtmp > 0) {
            frac64A += (lo >> (64 - noLZtmp));
            if (lo << noLZtmp) bitsMore = 1;
        } else {
            if (lo) bitsMore = 1;
        }
    }

    int kA = (71 - noLZ) >> 1;
    int8_t expA = 71 - noLZ - (kA << 1);

    uint16_t regA, regime, fracA = 0;
    bool bitNPlusOne = 0;

    if (kA < 0) { regA = (-kA) & 0xFFFF; regime = 0x4000 >> regA; }
    else        { regA = kA + 1; regime = 0x7FFF - (0x7FFF >> regA); }

    uint16_t uZ;
    if (regA > 14) {
        uZ = (kA >= 0) ? 0x7FFF : 0x1;
    } else {
        /* Remove hidden bit */
        frac64A &= 0x7FFFFFFFFFFFFFFFULL;
        uint16_t shift = regA + 50;
        fracA = frac64A >> shift;

        if (regA != 14) {
            bitNPlusOne = (frac64A >> (shift - 1)) & 0x1;
            if (frac64A << (65 - shift)) bitsMore = 1;
        } else if (frac64A > 0) {
            fracA = 0;
            bitsMore = 1;
        }
        if (regA == 14 && expA) bitNPlusOne = 1;

        uZ = _packToP16(regime, regA, expA, fracA);
        if (bitNPlusOne) {
            uZ += (uZ & 1) | bitsMore;
        }
    }

    if (sign) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}
