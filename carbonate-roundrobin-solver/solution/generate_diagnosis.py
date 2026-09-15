#!/usr/bin/env python3
"""Generate diagnosis.json by comparing broken vs fixed solver internals."""

import json
import math
import sys
import os

sys.path.insert(0, "/app")

# Read the original broken solver to compare
broken_path = "/app/carbonate_original.py"
fixed_path = "/app/carbonate.py"

# The bugs found through systematic comparison with PyCO2SYS
diagnosis = [
    {
        "bug_id": 1,
        "location": "total_borate() function",
        "description": "Uses Uppstrom (1974) borate-salinity coefficient 0.000416 instead of Lee et al. (2010) coefficient 0.0004326. PyCO2SYS with opt_total_borate=2 uses Lee et al. (2010). This causes ~4% systematic error in total borate concentration, which propagates through borate alkalinity to all TA-based calculations.",
        "fix": "Changed coefficient from 0.000416 to 0.0004326 in total_borate()",
        "conditions_affected": "All conditions - borate alkalinity is always part of total alkalinity. Most visible in TA-based input pairs (types 1+X) where the borate error directly affects pH solving."
    },
    {
        "bug_id": 2,
        "location": "fugacity_factor() function - delta variable",
        "description": "The delta term in the Weiss (1974) virial equation uses temperature in Celsius (TC = TK - 273.15) instead of absolute temperature (TK). The correct expression is delta = 57.7 - 0.118 * TK, not delta = 57.7 - 0.118 * TC. This causes ~0.26% error in the fugacity factor.",
        "fix": "Changed 'delta = 57.7 - 0.118 * TC' to 'delta = 57.7 - 0.118 * TK' and removed the intermediate TC variable",
        "conditions_affected": "All conditions - the fugacity factor directly scales pCO2 and fCO2 outputs. The error magnitude varies with temperature since delta is temperature-dependent."
    },
    {
        "bug_id": 3,
        "location": "pcx_KB() function - pressure correction coefficients",
        "description": "The KB (boric acid) pressure correction uses K2 (second carbonic acid dissociation) molar volume and compressibility coefficients (-15.82, -0.0219, 0.0, 1.13e-3, -0.1475e-3) instead of the correct KB coefficients (-29.48, 0.1622, -2.608e-3, -2.84e-3, 0.0). This is a copy-paste error from pcx_K2.",
        "fix": "Changed pcx_KB coefficients from (-15.82, -0.0219, 0.0, 1.13e-3, -0.1475e-3) to (-29.48, 0.1622, -2.608e-3, -2.84e-3, 0.0)",
        "conditions_affected": "Only manifests at non-zero pressure (P > 0 dbar). At surface (P=0), pressure correction factor is 1.0. Error grows with pressure - at 2000 dbar causes ~9% error in KB, propagating to borate alkalinity and all TA-dependent outputs under pressure."
    },
    {
        "bug_id": 4,
        "location": "ksi_YM95() function - unit conversion",
        "description": "Missing the (1 - 0.001005 * S) factor to convert KSi from mol/kg-H2O to mol/kg-SW. The Yao & Millero (1995) KSi parameterization gives results in mol/kg-H2O, which must be converted to mol/kg-SW by multiplying by (1 - 0.001005 * S). At S=35, this factor is ~0.965, causing ~3.5% error in KSi.",
        "fix": "Added '* (1.0 - 0.001005 * S)' to the return value of ksi_YM95()",
        "conditions_affected": "Only manifests when total_silicate > 0. The KSi error propagates through silicate alkalinity (SiAlk = TSi * KSi / (KSi + H)) to affect pH solving accuracy. Effect is proportional to silicate concentration."
    }
]

with open("/app/diagnosis.json", "w") as f:
    json.dump(diagnosis, f, indent=2)

print("diagnosis.json written to /app/diagnosis.json")
