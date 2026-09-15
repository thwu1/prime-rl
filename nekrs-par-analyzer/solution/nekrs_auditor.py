#!/usr/bin/env python3

"""nekRS simulation pre-flight auditor.

Cross-validates a Gmsh mesh file against a nekRS .par configuration file.
Outputs a JSON diagnostic report to stdout.
"""

import sys
import os
import json
import math
import re
import glob


# ============================================================================
# Safe math expression evaluator
# ============================================================================

_SAFE_NAMES = {
    "sqrt": math.sqrt,
    "abs": abs,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
}


def safe_eval_expr(expr_str):
    """Safely evaluate a mathematical expression string.

    Returns (value, error_message). On success error_message is None.
    """
    expr_str = expr_str.strip()
    if not expr_str:
        return None, "empty expression"

    # Allow digits, operators, parens, dots, whitespace, function names
    sanitized = expr_str
    for name in _SAFE_NAMES:
        sanitized = sanitized.replace(name, "")
    if re.search(r"[a-zA-Z_]", sanitized):
        return None, f"unknown identifier in expression: {expr_str}"

    try:
        result = eval(expr_str, {"__builtins__": {}}, _SAFE_NAMES)
        if isinstance(result, complex):
            return None, f"complex result for expression: {expr_str}"
        return float(result), None
    except ZeroDivisionError:
        return None, f"division by zero in expression: {expr_str}"
    except Exception as exc:
        return None, f"cannot evaluate expression '{expr_str}': {exc}"


# ============================================================================
# .par file parser
# ============================================================================

def parse_par_file(filepath):
    """Parse a nekRS .par file into a dict of sections.

    Returns dict: section_name (uppercase) -> dict of key -> raw_value_string.
    """
    sections = {}
    current_section = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\n\r")

            # Strip inline comments (# preceded by space or at start)
            comment_match = re.match(r"^(.*?)\s+#.*$", line)
            if comment_match:
                line = comment_match.group(1)
            elif line.lstrip().startswith("#"):
                continue

            line = line.strip()
            if not line:
                continue

            # Section header
            sec_match = re.match(r"^\[(.+)\]$", line)
            if sec_match:
                current_section = sec_match.group(1).strip().upper()
                if current_section not in sections:
                    sections[current_section] = {}
                continue

            # Key = value
            if "=" in line and current_section is not None:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip inline comment from value
                val_comment = re.match(r"^(.*?)\s+#.*$", value)
                if val_comment:
                    value = val_comment.group(1).strip()
                sections[current_section][key.lower()] = value

    return sections


def parse_compound_param(value_str):
    """Parse compound parameter like 'targetCFL=4.0+max=0.05+initial=1e-3'.

    Returns dict of sub-key -> sub-value (or True for flags).
    """
    parts = re.split(r"\s*\+\s*", value_str)
    result = {}
    for part in parts:
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip().lower()] = v.strip()
        elif part:
            result[part.strip().lower()] = True
    return result


def get_scalars(sections):
    """Extract declared scalar names from [GENERAL] scalars key."""
    general = sections.get("GENERAL", {})
    scalars_raw = general.get("scalars", "")
    if not scalars_raw:
        return []
    return [s.strip().upper() for s in scalars_raw.split(",") if s.strip()]


def get_material_props(sections):
    """Extract and evaluate material properties from field sections."""
    props = {}
    errors = []

    # Fluid velocity properties
    vel_section = sections.get("FLUID VELOCITY", {})
    for prop_name in ["viscosity", "rho"]:
        raw = vel_section.get(prop_name)
        if raw is not None:
            val, err = safe_eval_expr(raw)
            if err:
                errors.append({
                    "code": "EXPRESSION_ERROR",
                    "message": f"{prop_name}: {err}",
                    "section": "FLUID VELOCITY",
                    "key": prop_name,
                })
            else:
                props[prop_name] = val

    # Scalar properties
    scalars = get_scalars(sections)
    for scalar_name in scalars:
        sec_name = f"SCALAR {scalar_name}"
        sec = sections.get(sec_name, {})
        if not sec:
            # Try common aliases for temperature
            for alias in ["TEMPERATURE", "TEMP", "T"]:
                alt_name = f"SCALAR {alias}"
                if alt_name in sections and alt_name != sec_name:
                    sec = sections[alt_name]
                    break

        for prop_name in ["diffusioncoeff", "transportcoeff",
                          "diffusioncoeffsolid", "transportcoeffsolid"]:
            raw = sec.get(prop_name)
            if raw is not None:
                # Map to camelCase for output
                camel = prop_name
                if "solid" in prop_name:
                    base = prop_name.replace("solid", "")
                    camel = base + "Solid"
                if "diffusion" in prop_name and "solid" not in prop_name:
                    camel = "diffusionCoeff"
                elif "transport" in prop_name and "solid" not in prop_name:
                    camel = "transportCoeff"
                elif "diffusion" in prop_name and "solid" in prop_name:
                    camel = "diffusionCoeffSolid"
                elif "transport" in prop_name and "solid" in prop_name:
                    camel = "transportCoeffSolid"

                val, err = safe_eval_expr(raw)
                if err:
                    errors.append({
                        "code": "EXPRESSION_ERROR",
                        "message": f"{camel}: {err}",
                        "section": sec_name,
                        "key": prop_name,
                    })
                else:
                    props[camel] = val

    return props, errors


def get_boundary_conditions(sections, scalars):
    """Extract boundary condition maps for each field."""
    bcs = {}

    vel_sec = sections.get("FLUID VELOCITY", {})
    bc_raw = vel_sec.get("boundarytypemap", "")
    if bc_raw:
        bcs["velocity"] = [s.strip() for s in bc_raw.split(",") if s.strip()]

    for scalar_name in scalars:
        sec_name = f"SCALAR {scalar_name}"
        sec = sections.get(sec_name, {})
        bc_raw = sec.get("boundarytypemap", "")
        if bc_raw:
            bcs[scalar_name.lower()] = [s.strip() for s in bc_raw.split(",")
                                         if s.strip()]

    return bcs


# ============================================================================
# Physics detection
# ============================================================================

def detect_physics(sections, scalars):
    """Detect the physics type from parsed .par sections.

    Priority: rans_ktau > cht > pipe_flow > rbc > channel_flow > generic
    """
    has_k = "K" in scalars
    has_tau = "TAU" in scalars
    temp_names = {"TEMPERATURE", "TEMP", "T"}
    has_temp = bool(temp_names & set(scalars))
    has_const_flow = "constflowrate" in sections.get("GENERAL", {})

    # Check for solid mesh (CHT indicator)
    has_solid_mesh = False
    for scalar_name in scalars:
        sec = sections.get(f"SCALAR {scalar_name}", {})
        mesh_val = sec.get("mesh", "").lower().replace(" ", "")
        if "solid" in mesh_val:
            has_solid_mesh = True
            break

    # Detection priority
    if has_k and has_tau:
        return "rans_ktau"
    if has_solid_mesh:
        return "cht"
    if has_const_flow and not has_temp:
        return "pipe_flow"
    if has_temp:
        return "rbc"
    if not scalars and not has_const_flow:
        return "channel_flow"
    if has_const_flow:
        return "pipe_flow"
    return "generic"


def extract_nondim_params(physics_type, mat_props, sections):
    """Extract non-dimensional parameters based on physics type."""
    params = {}
    visc = mat_props.get("viscosity")
    diff = mat_props.get("diffusionCoeff")
    diff_solid = mat_props.get("diffusionCoeffSolid")

    if physics_type == "rbc":
        if visc and diff and visc > 0 and diff > 0:
            params["Pr"] = visc / diff
            params["Ra"] = 1.0 / (visc * diff)

    elif physics_type == "rans_ktau":
        if visc and visc > 0:
            params["Re"] = 1.0 / visc

    elif physics_type == "cht":
        if visc and visc > 0:
            params["Re"] = 1.0 / visc
        if visc and diff and visc > 0 and diff > 0:
            params["Pr"] = visc / diff
        if diff and diff_solid and diff > 0:
            params["conductivity_ratio"] = diff_solid / diff

    elif physics_type in ("pipe_flow", "channel_flow"):
        if visc and visc > 0:
            params["Re"] = 1.0 / visc

    # Extract flow direction for pipe/const-flow-rate cases
    general = sections.get("GENERAL", {})
    cfr_raw = general.get("constflowrate", "")
    if cfr_raw:
        compound = parse_compound_param(cfr_raw)
        direction = compound.get("direction", "")
        if direction:
            params["flow_direction"] = direction.upper()

    return params


# ============================================================================
# Validation
# ============================================================================

def validate_config(sections, scalars, physics_type, mat_props):
    """Check for configuration errors. Returns list of error dicts."""
    errors = []

    # 1. Missing scalar sections
    for scalar_name in scalars:
        sec_name = f"SCALAR {scalar_name}"
        if sec_name not in sections:
            errors.append({
                "code": "MISSING_SCALAR_SECTION",
                "message": f"Scalar '{scalar_name}' declared but no [{sec_name}] section found",
            })

    # 2. Invalid timestepper
    general = sections.get("GENERAL", {})
    ts = general.get("timestepper", "tombo2").lower()
    if ts not in ("tombo1", "tombo2", "tombo3"):
        errors.append({
            "code": "INVALID_TIMESTEPPER",
            "message": f"timeStepper '{ts}' is not tombo1/tombo2/tombo3",
        })

    # 3. RANS requires variableViscosity
    if physics_type == "rans_ktau":
        pt_sec = sections.get("PROBLEMTYPE", {})
        eq = pt_sec.get("equation", "").lower().replace(" ", "")
        if "variableviscosity" not in eq:
            errors.append({
                "code": "MISSING_VARIABLE_VISCOSITY",
                "message": "RANS k-tau requires equation=navierStokes+variableViscosity",
            })

    # 4. Negative properties
    for prop_name in ["viscosity", "rho", "diffusionCoeff", "transportCoeff"]:
        val = mat_props.get(prop_name)
        if val is not None and val <= 0:
            errors.append({
                "code": "NEGATIVE_PROPERTY",
                "message": f"{prop_name} = {val} (must be > 0)",
            })

    # 5. CHT requires solid coefficients
    for scalar_name in scalars:
        sec_name = f"SCALAR {scalar_name}"
        sec = sections.get(sec_name, {})
        mesh_val = sec.get("mesh", "").lower().replace(" ", "")
        if "solid" in mesh_val:
            if "diffusioncoeffsolid" not in sec:
                errors.append({
                    "code": "MISSING_SOLID_DIFFUSION",
                    "message": f"[{sec_name}] has mesh=fluid+solid but no diffusionCoeffSolid",
                })
            if "transportcoeffsolid" not in sec:
                errors.append({
                    "code": "MISSING_SOLID_TRANSPORT",
                    "message": f"[{sec_name}] has mesh=fluid+solid but no transportCoeffSolid",
                })

    # 6. Polynomial order range
    poly_raw = general.get("polynomialorder", "7")
    try:
        poly = int(poly_raw)
        if poly < 1 or poly > 15:
            errors.append({
                "code": "INVALID_POLYNOMIAL_ORDER",
                "message": f"polynomialOrder={poly} outside valid range [1, 15]",
            })
    except ValueError:
        pass

    # 7. Flow direction validity
    cfr_raw = general.get("constflowrate", "")
    if cfr_raw:
        compound = parse_compound_param(cfr_raw)
        direction = compound.get("direction", "")
        if direction and direction.upper() not in ("X", "Y", "Z"):
            errors.append({
                "code": "INVALID_FLOW_DIRECTION",
                "message": f"constFlowRate direction='{direction}' not in {{X, Y, Z}}",
            })

    # 8. Regularization scaling coefficient range
    reg_raw = general.get("regularization", "")
    if reg_raw:
        compound = parse_compound_param(reg_raw)
        sc_raw = compound.get("scalingcoeff", "")
        if sc_raw and sc_raw is not True:
            try:
                sc_val = float(sc_raw)
                if sc_val < 0.5 or sc_val > 50:
                    errors.append({
                        "code": "SCALING_COEFF_OUT_OF_RANGE",
                        "message": f"regularization scalingCoeff={sc_val} outside [0.5, 50]",
                    })
            except ValueError:
                pass

    return errors


# ============================================================================
# Mesh analysis via gmsh Python API
# ============================================================================

def analyze_mesh(msh_file):
    """Analyze a Gmsh mesh file. Returns mesh statistics dict."""
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.open(msh_file)

    # Determine dimension
    dim = gmsh.model.getDimension()

    # Bounding box
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)

    # Get surface (2D) or volume (3D) elements
    elem_types, elem_tags_nested, node_tags_nested = gmsh.model.mesh.getElements(dim)
    all_elem_tags = []
    for tags in elem_tags_nested:
        all_elem_tags.extend(tags)
    num_elements = len(all_elem_tags)

    # Element sizes (areas for 2D, volumes for 3D)
    # Compute from node coordinates
    node_tag_map, node_coords, _ = gmsh.model.mesh.getNodes()
    coord_dict = {}
    for i, tag in enumerate(node_tag_map):
        coord_dict[tag] = (node_coords[3 * i], node_coords[3 * i + 1],
                           node_coords[3 * i + 2])

    element_sizes = []
    element_edge_lengths = []

    for et_idx, etype in enumerate(elem_types):
        props = gmsh.model.mesh.getElementProperties(etype)
        elem_name, elem_dim, elem_order, num_nodes_per, _, _ = props
        tags = elem_tags_nested[et_idx]
        nodes = node_tags_nested[et_idx]

        for i in range(len(tags)):
            enodes = nodes[i * num_nodes_per: (i + 1) * num_nodes_per]
            coords = [coord_dict[int(n)] for n in enodes]

            if num_nodes_per == 4 and dim == 2:
                # Quad: area via cross product of diagonals / 2
                # or shoelace formula
                x = [c[0] for c in coords]
                y = [c[1] for c in coords]
                area = 0.5 * abs(
                    (x[0] * y[1] - x[1] * y[0]) +
                    (x[1] * y[2] - x[2] * y[1]) +
                    (x[2] * y[3] - x[3] * y[2]) +
                    (x[3] * y[0] - x[0] * y[3])
                )
                element_sizes.append(area)

                # Edge lengths
                for j in range(4):
                    j2 = (j + 1) % 4
                    dx = coords[j2][0] - coords[j][0]
                    dy = coords[j2][1] - coords[j][1]
                    dz = coords[j2][2] - coords[j][2]
                    elen = math.sqrt(dx * dx + dy * dy + dz * dz)
                    element_edge_lengths.append(elen)

            elif num_nodes_per == 3 and dim == 2:
                # Triangle
                x = [c[0] for c in coords]
                y = [c[1] for c in coords]
                area = 0.5 * abs(
                    (x[1] - x[0]) * (y[2] - y[0]) -
                    (x[2] - x[0]) * (y[1] - y[0])
                )
                element_sizes.append(area)
                for j in range(3):
                    j2 = (j + 1) % 3
                    dx = coords[j2][0] - coords[j][0]
                    dy = coords[j2][1] - coords[j][1]
                    elen = math.sqrt(dx * dx + dy * dy)
                    element_edge_lengths.append(elen)
            else:
                # Fallback: estimate from bounding box of element nodes
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                zs = [c[2] for c in coords]
                size = (max(xs) - min(xs)) * max(max(ys) - min(ys), 1e-30)
                element_sizes.append(size)

    min_size = min(element_sizes) if element_sizes else 0.0
    max_size = max(element_sizes) if element_sizes else 0.0
    min_edge = min(element_edge_lengths) if element_edge_lengths else 0.0

    # Element quality
    mean_quality = 0.0
    if all_elem_tags:
        try:
            qualities = gmsh.model.mesh.getElementQualities(all_elem_tags)
            mean_quality = sum(qualities) / len(qualities) if qualities else 0.0
        except Exception:
            mean_quality = 0.0

    # Boundary physical groups (dim-1 entities)
    boundary_groups = {}
    phys_groups = gmsh.model.getPhysicalGroups(dim - 1)
    for pg_dim, pg_tag in phys_groups:
        name = gmsh.model.getPhysicalName(pg_dim, pg_tag)
        entities = gmsh.model.getEntitiesForPhysicalGroup(pg_dim, pg_tag)
        count = 0
        for entity in entities:
            _, etags, _ = gmsh.model.mesh.getElements(pg_dim, entity)
            for t in etags:
                count += len(t)
        boundary_groups[name] = count

    gmsh.finalize()

    return {
        "num_elements": num_elements,
        "dimension": dim,
        "bounding_box": [
            [round(xmin, 10), round(ymin, 10), round(zmin, 10)],
            [round(xmax, 10), round(ymax, 10), round(zmax, 10)],
        ],
        "min_element_size": min_size,
        "max_element_size": max_size,
        "mean_quality": mean_quality,
        "boundary_groups": boundary_groups,
        "_min_edge_length": min_edge,  # internal, used for GLL spacing
    }


# ============================================================================
# GLL point spacing computation
# ============================================================================

def gll_first_fraction(N):
    """Compute the normalized distance of the first GLL interior point
    from the element boundary for polynomial order N.

    Returns fraction in [0, 0.5] such that physical distance =
    fraction * element_edge_length.
    """
    if N <= 1:
        return 0.5

    # Compute GLL points on [-1, 1] using Newton's method
    # Initial guess: Chebyshev-Gauss-Lobatto points
    x = [-math.cos(math.pi * i / N) for i in range(N + 1)]

    for _ in range(100):
        converged = True
        for i in range(1, N):
            xi = x[i]

            # Legendre polynomial via three-term recurrence
            P_prev = 1.0  # P_0
            P_curr = xi    # P_1
            for k in range(2, N + 1):
                P_next = ((2 * k - 1) * xi * P_curr - (k - 1) * P_prev) / k
                P_prev = P_curr
                P_curr = P_next

            # P'_N(xi) = N * (xi * P_N - P_{N-1}) / (xi^2 - 1)
            denom = xi * xi - 1.0
            if abs(denom) < 1e-30:
                continue
            dP = N * (xi * P_curr - P_prev) / denom

            # From Legendre ODE: (1-x^2)P'' = 2xP' - N(N+1)P
            # Since denom = x^2-1 = -(1-x^2):
            # P''_N = -(2*xi*P'_N - N*(N+1)*P_N) / denom
            d2P = -(2.0 * xi * dP - N * (N + 1) * P_curr) / denom

            if abs(d2P) < 1e-30:
                continue

            delta = dP / d2P
            x[i] = xi - delta
            if abs(delta) > 1e-15:
                converged = False

        if converged:
            break

    x.sort()
    # Distance from -1 to first interior point, mapped to [0,1]
    first_dist = (x[1] - x[0]) / 2.0
    return first_dist


def estimate_y_plus(physics_type, nondim_params, first_gll_dist):
    """Estimate y+ at the first GLL point for wall-bounded flows.

    Uses Dean's correlation: Re_tau ≈ 0.09 * Re_b^0.88
    y+ = first_gll_dist * Re_tau
    """
    Re = nondim_params.get("Re")

    if Re is None or Re <= 0:
        return None

    if physics_type == "rbc":
        # Buoyancy-driven: no bulk Re in the standard sense
        return None

    # Dean's correlation for friction Reynolds number
    Re_tau = 0.09 * Re ** 0.88
    y_plus = first_gll_dist * Re_tau

    return y_plus


# ============================================================================
# Main
# ============================================================================

def analyze_config(par_file):
    """Full analysis of a .par configuration file."""
    sections = parse_par_file(par_file)
    scalars = get_scalars(sections)

    # Material properties (with expression eval errors)
    mat_props, expr_errors = get_material_props(sections)

    # Physics detection
    physics_type = detect_physics(sections, scalars)

    # Non-dimensional parameters
    nondim_params = extract_nondim_params(physics_type, mat_props, sections)

    # Boundary conditions
    boundary_conditions = get_boundary_conditions(sections, scalars)

    # Validation
    validation_errors = validate_config(sections, scalars, physics_type, mat_props)

    # Combine errors
    all_errors = expr_errors + validation_errors

    # General parameters
    general = sections.get("GENERAL", {})
    poly_order = 7
    try:
        poly_order = int(general.get("polynomialorder", "7"))
    except ValueError:
        pass

    time_stepper = general.get("timestepper", "tombo2").lower()

    return {
        "physics_type": physics_type,
        "polynomial_order": poly_order,
        "time_stepper": time_stepper,
        "scalars": [s.lower() for s in scalars],
        "material_props": mat_props,
        "nondim_params": nondim_params,
        "boundary_conditions": boundary_conditions,
        "errors": [{"code": e["code"], "message": e["message"]} for e in all_errors],
        "valid": len(all_errors) == 0,
    }


def compute_diagnostics(config, mesh_stats):
    """Compute cross-validated diagnostics."""
    N = config["polynomial_order"]
    dim = mesh_stats["dimension"] if mesh_stats else 2
    num_elem = mesh_stats["num_elements"] if mesh_stats else 0

    # Total degrees of freedom
    total_dof = num_elem * (N + 1) ** dim

    # GLL spacing
    gll_frac = gll_first_fraction(N)
    min_edge = mesh_stats.get("_min_edge_length", 0.0) if mesh_stats else 0.0
    first_gll_spacing = min_edge * gll_frac

    # y+ estimation
    y_plus = estimate_y_plus(
        config["physics_type"],
        config["nondim_params"],
        first_gll_spacing,
    )

    return {
        "total_dof": total_dof,
        "first_gll_spacing": first_gll_spacing,
        "estimated_y_plus": y_plus,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: nekrs_auditor.py <case_dir>", file=sys.stderr)
        sys.exit(1)

    case_dir = sys.argv[1]

    # Find files
    par_files = glob.glob(os.path.join(case_dir, "*.par"))
    msh_files = glob.glob(os.path.join(case_dir, "*.msh"))

    if not par_files:
        print(json.dumps({"error": "No .par file found in " + case_dir}))
        sys.exit(0)

    # Analyze config
    config = analyze_config(par_files[0])

    # Analyze mesh
    mesh_stats = None
    if msh_files:
        mesh_stats = analyze_mesh(msh_files[0])

    # Compute diagnostics
    diagnostics = compute_diagnostics(config, mesh_stats)

    # Build output — remove internal fields from mesh stats
    mesh_output = None
    if mesh_stats:
        mesh_output = {k: v for k, v in mesh_stats.items()
                       if not k.startswith("_")}

    result = {
        "mesh": mesh_output,
        "config": config,
        "diagnostics": diagnostics,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
