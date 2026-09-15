/*
 * posit16.c — Posit16 arithmetic library implementation
 *
 * Some operations are working correctly (p16_to_f64, p16_add, p16_sub).
 * Others need to be fixed or implemented from scratch.
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
 * Conversion: posit16 -> double  [WORKING]
 * ===================================================================== */
double p16_to_f64(posit16_t a) {
    uint16_t uiA = a.v;

    if (uiA == 0)      return 0.0;
    if (uiA == 0x7FFF)  return 268435456.0;    /* maxpos   */
    if (uiA == 0x8001)  return -268435456.0;   /* -maxpos  */
    if (uiA == 0x8000)  return NAN;            /* NaR      */

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
 * Addition: same-sign magnitude helper  [WORKING]
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
 * Subtraction: different-sign magnitude helper  [WORKING]
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
 * p16_add  [WORKING]
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
 * p16_sub  [WORKING]
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
 * p16_mul  [CONTAINS A BUG — produces incorrect results for some inputs]
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
            uZ += 1;   /* rounding applied here */
        }
    }

    if (signZ) uZ = (-uZ) & 0xFFFF;
    return (posit16_t){uZ};
}

/* =====================================================================
 * p16_div  [TODO: implement posit16 division]
 * ===================================================================== */
posit16_t p16_div(posit16_t a, posit16_t b) {
    (void)a; (void)b;
    /* TODO: Implement posit16 division with correct rounding */
    return P16_NAR;
}

/* =====================================================================
 * Quire operations
 * ===================================================================== */

quire16_t q16_clr(void) {
    quire16_t q;
    q.v[0] = 0;
    q.v[1] = 0;
    return q;
}

quire16_t q16_fdp_add(quire16_t q, posit16_t a, posit16_t b) {
    (void)a; (void)b;
    /* TODO: Implement quire16 fused dot-product accumulation.
     * Compute the exact product a*b and add it to the 128-bit quire
     * without intermediate rounding. */
    return q;
}

posit16_t q16_to_p16(quire16_t q) {
    (void)q;
    /* TODO: Convert quire16 accumulator to posit16 with a single
     * round-to-nearest-even step. */
    return P16_ZERO;
}
