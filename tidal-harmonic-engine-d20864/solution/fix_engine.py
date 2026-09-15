#!/usr/bin/env python3
"""
Fix defects in the tidal prediction engine.

C library bugs (astro.c + Makefile):
1. normalize_angle uses C fmod() which preserves sign for negative angles.
   Fix: add conditional correction for negative results.
2. Makefile defines -DNODE_RATE=0.05295377 (positive), but the ascending
   lunar node regresses, so the correct rate is negative (-0.05295377).
   Fix: correct the sign in the Makefile -D flag.

Python engine bugs (tidal_engine.py):
3. angular_frequency missing 2*pi factor in degrees-to-radians conversion.
4. harmonic_analysis design matrix uses +sin instead of -sin.
5. predict_tide missing nodal amplitude factor pf[:, k].

Data corruption (doodson_coefficients.json):
6. nu2 p-coefficient (index 3) is 0, should be -1.
7. mu2 p-coefficient (index 3) is 1, should be 0.
8. l2 p-coefficient (index 3) is 0, should be -1.
"""
import json


def fix_c_library():
    """Fix the C library source and Makefile."""
    # Fix 1: normalize_angle - handle negative angles from fmod
    with open("/app/libastro/astro.c", "r") as f:
        code = f.read()
    code = code.replace(
        "return fmod(angle, 360.0);",
        "double r = fmod(angle, 360.0); return r < 0.0 ? r + 360.0 : r;"
    )
    with open("/app/libastro/astro.c", "w") as f:
        f.write(code)

    # Fix 2: Makefile - correct NODE_RATE sign
    with open("/app/libastro/Makefile", "r") as f:
        mk = f.read()
    mk = mk.replace(
        "-DNODE_RATE=0.05295377",
        "-DNODE_RATE=-0.05295377"
    )
    with open("/app/libastro/Makefile", "w") as f:
        f.write(mk)


def fix_python_engine():
    """Fix the three Python bugs in tidal_engine.py."""
    with open("/app/tidal_engine.py", "r") as f:
        code = f.read()

    # Fix 3: angular_frequency - add 2*pi factor
    code = code.replace(
        "omega = fd / 360.0",
        "omega = 2.0 * np.pi * fd / 360.0"
    )

    # Fix 4: harmonic_analysis - negate sine term in design matrix
    code = code.replace(
        "        M.append(pf[:, k] * np.sin(th))\n    M = np.transpose(M)",
        "        M.append(-pf[:, k] * np.sin(th))\n    M = np.transpose(M)"
    )

    # Fix 5: predict_tide - multiply by nodal amplitude factor
    code = code.replace(
        "        heights += z.real * np.cos(th) - z.imag * np.sin(th)",
        "        heights += pf[:, k] * (z.real * np.cos(th) - z.imag * np.sin(th))"
    )

    with open("/app/tidal_engine.py", "w") as f:
        f.write(code)


def fix_json():
    """Fix corrupted Doodson coefficient entries."""
    with open("/app/doodson_coefficients.json", "r") as f:
        data = json.load(f)

    # Fix 6: nu2 p-coefficient should be -1, not 0
    data["nu2"][3] = -1.0

    # Fix 7: mu2 p-coefficient should be 0, not 1
    data["mu2"][3] = 0.0

    # Fix 8: l2 p-coefficient should be -1, not 0
    data["l2"][3] = -1.0

    with open("/app/doodson_coefficients.json", "w") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    fix_c_library()
    fix_python_engine()
    fix_json()
    print("All fixes applied.")
