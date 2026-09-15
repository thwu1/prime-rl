#!/usr/bin/env python3
"""
nekRS .par configuration file analyzer.

Parses nekRS spectral-element CFD solver .par files, detects simulation physics
type, extracts non-dimensional parameters, and validates internal consistency.

Usage: python3 nekrs_analyzer.py <par_file>
Output: JSON to stdout
"""

import sys
import json
import re
import math


# ---------------------------------------------------------------------------
# Expression evaluation
# ---------------------------------------------------------------------------

def evaluate_expression(expr_str):
    """
    Safely evaluate a nekRS mathematical expression to a float.

    Returns (value, error_message) tuple:
      - (float, None)   on success
      - (None, str)      on evaluation failure (syntax error, div-by-zero, etc.)
      - (None, None)     when the value is not a numeric expression (string/compound)
    """
    expr_str = expr_str.strip()

    # Strip inline comments (whitespace + #)
    idx = expr_str.find(" #")
    if idx >= 0:
        expr_str = expr_str[:idx].strip()

    if not expr_str:
        return None, "Empty expression"

    # Compound parameters (contain =) are not numeric
    if "=" in expr_str:
        return None, None

    # Determine if the expression is numeric or a plain string.
    # Remove known math function names and scientific-notation letters,
    # then check for any remaining alphabetic characters.
    test_str = expr_str
    for fn in ("sqrt", "exp", "log", "sin", "cos", "tan", "abs", "pow", "pi"):
        test_str = re.sub(r"\b" + fn + r"\b", "", test_str)
    # Remove e/E in scientific notation context (e.g. 1e8, 6.0e-3)
    test_str = re.sub(r"\d[eE][+-]?\d", "", test_str)
    if re.search(r"[a-zA-Z]", test_str):
        return None, None  # pure string value

    try:
        safe = expr_str
        safe = re.sub(r"\bsqrt\b", "math.sqrt", safe)
        safe = re.sub(r"\bexp\b", "math.exp", safe)
        safe = re.sub(r"\blog\b", "math.log", safe)
        safe = re.sub(r"\bsin\b", "math.sin", safe)
        safe = re.sub(r"\bcos\b", "math.cos", safe)
        safe = re.sub(r"\btan\b", "math.tan", safe)
        safe = re.sub(r"\babs\b", "abs", safe)
        safe = re.sub(r"\bpow\b", "math.pow", safe)
        safe = re.sub(r"\bpi\b", str(math.pi), safe)

        result = eval(safe, {"__builtins__": {}, "math": math, "abs": abs})
        return float(result), None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# .par file parser
# ---------------------------------------------------------------------------

def parse_par_file(filepath):
    """
    Parse a nekRS .par file into {section_name: {key: raw_value}}.
    """
    sections = {}
    current_section = None

    with open(filepath) as fh:
        for raw_line in fh:
            line = raw_line.strip()

            # Skip blank lines and full-line comments
            if not line or line.startswith("#"):
                continue

            # Section header
            match = re.match(r"^\[(.+)\]$", line)
            if match:
                current_section = match.group(1).strip()
                sections.setdefault(current_section, {})
                continue

            # Key = value  (split on first '=' only)
            if "=" in line and current_section is not None:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                # Strip inline comments (space + #)
                cidx = value.find(" #")
                if cidx >= 0:
                    value = value[:cidx].strip()

                sections[current_section][key] = value

    return sections


# ---------------------------------------------------------------------------
# Compound parameter helper
# ---------------------------------------------------------------------------

def extract_compound_param(value_str, subkey):
    """
    Extract a sub-parameter from a compound value.
    E.g. extract_compound_param("meanVelocity=1.0 + direction=Z", "direction") -> "Z"
    """
    for part in re.split(r"\s*\+\s*", value_str):
        if "=" in part:
            k, _, v = part.partition("=")
            if k.strip().lower() == subkey.lower():
                return v.strip()
    return None


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------

def get_scalar_names(sections):
    """Return the list of scalar names declared in [GENERAL] scalars."""
    general = sections.get("GENERAL", {})
    raw = general.get("scalars", "")
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Physics type detection
# ---------------------------------------------------------------------------

_TEMP_NAMES = {"TEMPERATURE", "TEMP", "T"}


def detect_physics_type(sections):
    """Detect the simulation physics type from configuration patterns."""
    scalar_names_upper = [s.upper() for s in get_scalar_names(sections)]
    general = sections.get("GENERAL", {})

    # Priority 1: RANS k-tau (K + TAU scalars)
    if "K" in scalar_names_upper and "TAU" in scalar_names_upper:
        return "rans_ktau"

    # Priority 2: CHT (temperature scalar with solid mesh)
    for sname in get_scalar_names(sections):
        sec = sections.get(f"SCALAR {sname}", {})
        if "solid" in sec.get("mesh", "").lower():
            return "cht"

    # Priority 3: pipe_flow (constFlowRate present)
    if "constFlowRate" in general:
        return "pipe_flow"

    # Priority 4: RBC (temperature-like scalar)
    if any(s in _TEMP_NAMES for s in scalar_names_upper):
        return "rbc"

    # Priority 5: channel_flow (no scalars)
    if not scalar_names_upper:
        return "channel_flow"

    return "generic"


# ---------------------------------------------------------------------------
# Non-dimensional parameter extraction
# ---------------------------------------------------------------------------

def extract_nondim_params(sections, physics_type):
    """Compute non-dimensional parameters appropriate for the physics type."""
    params = {}
    vel = sections.get("FLUID VELOCITY", {})
    viscosity, _ = evaluate_expression(vel.get("viscosity", ""))

    if physics_type == "rbc":
        for sname in get_scalar_names(sections):
            sec = sections.get(f"SCALAR {sname}", {})
            diff, _ = evaluate_expression(sec.get("diffusionCoeff", ""))
            if viscosity and diff and viscosity > 0 and diff > 0:
                params["Pr"] = viscosity / diff
                params["Ra"] = 1.0 / (viscosity * diff)
            break

    elif physics_type == "rans_ktau":
        if viscosity and viscosity > 0:
            params["Re"] = 1.0 / viscosity

    elif physics_type == "cht":
        if viscosity and viscosity > 0:
            params["Re"] = 1.0 / viscosity
        for sname in get_scalar_names(sections):
            sec = sections.get(f"SCALAR {sname}", {})
            diff, _ = evaluate_expression(sec.get("diffusionCoeff", ""))
            diff_s, _ = evaluate_expression(sec.get("diffusionCoeffSolid", ""))
            if viscosity and diff and viscosity > 0 and diff > 0:
                params["Pr"] = viscosity / diff
            if diff and diff_s and diff > 0:
                params["conductivity_ratio"] = diff_s / diff
            break

    elif physics_type == "pipe_flow":
        if viscosity and viscosity > 0:
            params["Re"] = 1.0 / viscosity
        general = sections.get("GENERAL", {})
        direction = extract_compound_param(
            general.get("constFlowRate", ""), "direction"
        )
        if direction:
            params["flow_direction"] = direction

    elif physics_type == "channel_flow":
        if viscosity and viscosity > 0:
            params["Re"] = 1.0 / viscosity

    return params


# ---------------------------------------------------------------------------
# Material properties
# ---------------------------------------------------------------------------

def extract_material_props(sections):
    """Evaluate material property values from the configuration."""
    props = {}
    vel = sections.get("FLUID VELOCITY", {})
    for key in ("viscosity", "rho"):
        if key in vel:
            val, _ = evaluate_expression(vel[key])
            if val is not None:
                props[key] = val

    for sname in get_scalar_names(sections):
        sec = sections.get(f"SCALAR {sname}", {})
        for key in ("diffusionCoeff", "transportCoeff",
                     "diffusionCoeffSolid", "transportCoeffSolid"):
            if key in sec:
                val, _ = evaluate_expression(sec[key])
                if val is not None:
                    props[key] = val

    return props


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

def extract_boundary_conditions(sections):
    """Extract boundary-condition type lists for each field."""
    bcs = {}
    vel = sections.get("FLUID VELOCITY", {})
    if "boundaryTypeMap" in vel:
        bcs["velocity"] = [s.strip() for s in vel["boundaryTypeMap"].split(",")]

    for sname in get_scalar_names(sections):
        sec = sections.get(f"SCALAR {sname}", {})
        if "boundaryTypeMap" in sec:
            bcs[sname.lower()] = [
                s.strip() for s in sec["boundaryTypeMap"].split(",")
            ]

    return bcs


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(sections):
    """Run all validation rules. Returns a list of error dicts."""
    errors = []
    general = sections.get("GENERAL", {})
    scalar_names = get_scalar_names(sections)

    # ---- 1. Scalar section existence ----
    for sname in scalar_names:
        sec_key = f"SCALAR {sname}"
        if sec_key not in sections:
            errors.append({
                "code": "MISSING_SCALAR_SECTION",
                "message": (
                    f"Scalar '{sname}' declared in [GENERAL] scalars "
                    f"but no [{sec_key}] section found"
                ),
                "section": "GENERAL",
                "key": "scalars",
            })

    # ---- 2. Numeric field evaluation ----
    numeric_fields = [
        ("FLUID VELOCITY", "viscosity"),
        ("FLUID VELOCITY", "rho"),
    ]
    for sname in scalar_names:
        sec_key = f"SCALAR {sname}"
        if sec_key in sections:
            for prop in ("diffusionCoeff", "transportCoeff"):
                if prop in sections[sec_key]:
                    numeric_fields.append((sec_key, prop))

    for section, key in numeric_fields:
        if section in sections and key in sections[section]:
            val, err = evaluate_expression(sections[section][key])
            if err is not None:
                errors.append({
                    "code": "EXPRESSION_ERROR",
                    "message": (
                        f"Cannot evaluate '{sections[section][key]}' "
                        f"for {key} in [{section}]: {err}"
                    ),
                    "section": section,
                    "key": key,
                })
            elif val is not None and val <= 0:
                errors.append({
                    "code": "NEGATIVE_PROPERTY",
                    "message": (
                        f"{key} = {val} is not positive in [{section}]"
                    ),
                    "section": section,
                    "key": key,
                })

    # ---- 3. timeStepper ----
    ts = general.get("timeStepper", "")
    if ts and ts not in ("tombo1", "tombo2", "tombo3"):
        errors.append({
            "code": "INVALID_TIMESTEPPER",
            "message": (
                f"Invalid timeStepper '{ts}'; "
                f"must be tombo1, tombo2, or tombo3"
            ),
            "section": "GENERAL",
            "key": "timeStepper",
        })

    # ---- 4. polynomialOrder ----
    po_str = general.get("polynomialOrder", "")
    if po_str:
        po_val, _ = evaluate_expression(po_str)
        if po_val is not None:
            po_int = int(po_val)
            if po_int < 1 or po_int > 15:
                errors.append({
                    "code": "INVALID_POLYNOMIAL_ORDER",
                    "message": (
                        f"polynomialOrder = {po_int} "
                        f"outside valid range [1, 15]"
                    ),
                    "section": "GENERAL",
                    "key": "polynomialOrder",
                })

    # ---- 5. RANS k-tau requires variableViscosity ----
    upper_scalars = [s.upper() for s in scalar_names]
    if "K" in upper_scalars and "TAU" in upper_scalars:
        pt = sections.get("PROBLEMTYPE", {})
        eq = pt.get("equation", "")
        if "variableViscosity" not in eq:
            errors.append({
                "code": "MISSING_VARIABLE_VISCOSITY",
                "message": (
                    "RANS k-tau (K+TAU scalars) requires "
                    "equation = navierStokes+variableViscosity"
                ),
                "section": "PROBLEMTYPE",
                "key": "equation",
            })

    # ---- 6. CHT solid properties ----
    for sname in scalar_names:
        sec_key = f"SCALAR {sname}"
        if sec_key in sections:
            mesh_val = sections[sec_key].get("mesh", "").lower()
            if "solid" in mesh_val:
                if "diffusionCoeffSolid" not in sections[sec_key]:
                    errors.append({
                        "code": "MISSING_SOLID_DIFFUSION",
                        "message": (
                            f"[{sec_key}] has mesh=fluid+solid "
                            f"but missing diffusionCoeffSolid"
                        ),
                        "section": sec_key,
                        "key": "diffusionCoeffSolid",
                    })
                if "transportCoeffSolid" not in sections[sec_key]:
                    errors.append({
                        "code": "MISSING_SOLID_TRANSPORT",
                        "message": (
                            f"[{sec_key}] has mesh=fluid+solid "
                            f"but missing transportCoeffSolid"
                        ),
                        "section": sec_key,
                        "key": "transportCoeffSolid",
                    })

    # ---- 7. constFlowRate direction ----
    cfr = general.get("constFlowRate", "")
    if cfr:
        direction = extract_compound_param(cfr, "direction")
        if direction and direction not in ("X", "Y", "Z"):
            errors.append({
                "code": "INVALID_FLOW_DIRECTION",
                "message": (
                    f"constFlowRate direction '{direction}' invalid; "
                    f"must be X, Y, or Z"
                ),
                "section": "GENERAL",
                "key": "constFlowRate",
            })

    # ---- 8. regularization scalingCoeff ----
    reg = general.get("regularization", "")
    if reg:
        sc_str = extract_compound_param(reg, "scalingCoeff")
        if sc_str:
            sc_val, _ = evaluate_expression(sc_str)
            if sc_val is not None and (sc_val < 0.5 or sc_val > 50):
                errors.append({
                    "code": "SCALING_COEFF_OUT_OF_RANGE",
                    "message": (
                        f"regularization scalingCoeff = {sc_val} "
                        f"outside valid range [0.5, 50]"
                    ),
                    "section": "GENERAL",
                    "key": "regularization",
                })

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python3 nekrs_analyzer.py <par_file>"}))
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        sections = parse_par_file(filepath)
    except Exception as exc:
        print(json.dumps({"error": f"Failed to parse file: {exc}"}))
        sys.exit(1)

    physics_type = detect_physics_type(sections)
    nondim_params = extract_nondim_params(sections, physics_type)
    material_props = extract_material_props(sections)
    boundary_conditions = extract_boundary_conditions(sections)
    validation_errors = validate(sections)

    general = sections.get("GENERAL", {})
    po_val, _ = evaluate_expression(general.get("polynomialOrder", "0"))

    result = {
        "physics_type": physics_type,
        "polynomial_order": int(po_val) if po_val else 0,
        "time_stepper": general.get("timeStepper", ""),
        "nondim_params": nondim_params,
        "material_props": material_props,
        "boundary_conditions": boundary_conditions,
        "errors": validation_errors,
        "valid": len(validation_errors) == 0,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
