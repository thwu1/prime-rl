#!/usr/bin/env python3
"""
Pairing-friendly curve cross-validation audit tool.

Parses heterogeneous parameter sources (PARI/GP scripts, hex files, inline TOML),
validates curve integrity, estimates cryptographic security, and generates
a PARI/GP verification script.
"""


import json
import math
import os
import random
import subprocess
import tomllib


def is_probable_prime(n, k=25):
    """Miller-Rabin primality test with k witnesses."""
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False
    small_primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
    for sp in small_primes:
        if n == sp:
            return True
        if n % sp == 0:
            return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    rng = random.Random(42)
    for _ in range(k):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def parse_hex(s):
    """Parse a hex string with optional negative sign and 0x prefix."""
    s = s.strip()
    neg = False
    if s.startswith("-"):
        neg = True
        s = s[1:]
    if s.lower().startswith("0x"):
        s = s[2:]
    val = int(s, 16)
    return -val if neg else val


def run_gp_script(path):
    """Execute a PARI/GP script and parse PARAM_X=value output."""
    result = subprocess.run(
        ["gp", "-q", path],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"GP script {path} failed: {result.stderr}")
    params = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "=" in line and line.startswith("PARAM_"):
            key, val = line.split("=", 1)
            params[key.strip()] = int(val.strip())
    return params


def read_hex_file(path):
    """Read a hex file and return the integer value."""
    with open(path) as f:
        return int(f.read().strip(), 16)


def extract_params(curve_def, base_dir="/app"):
    """Extract u, p, r from a curve definition using the appropriate source."""
    u = p = r = None

    if "params_gp" in curve_def:
        gp_path = os.path.join(base_dir, curve_def["params_gp"])
        params = run_gp_script(gp_path)
        u = params["PARAM_U"]
        p = params["PARAM_P"]
        r = params["PARAM_R"]
    else:
        if "u_hex" in curve_def:
            u = parse_hex(curve_def["u_hex"])
        if "p_hex" in curve_def:
            p = parse_hex(curve_def["p_hex"])
        elif "p_hex_file" in curve_def:
            p = read_hex_file(os.path.join(base_dir, curve_def["p_hex_file"]))
        if "r_hex" in curve_def:
            r = parse_hex(curve_def["r_hex"])
        elif "r_hex_file" in curve_def:
            r = read_hex_file(os.path.join(base_dir, curve_def["r_hex_file"]))

    return u, p, r


# --- Family polynomial definitions ---

def bls12_p(u):
    num = (u - 1) ** 2 * (u ** 4 - u ** 2 + 1)
    if num % 3 != 0:
        return None
    return num // 3 + u


def bls12_r(u):
    return u ** 4 - u ** 2 + 1


def bn_p(u):
    return 36 * u**4 + 36 * u**3 + 24 * u**2 + 6 * u + 1


def bn_r(u):
    return 36 * u**4 + 36 * u**3 + 18 * u**2 + 6 * u + 1


FAMILY_POLYS = {
    "BLS12": (bls12_p, bls12_r),
    "BN": (bn_p, bn_r),
}


def validate_curve(u, p, r, k, family):
    """Validate a curve's algebraic parameters. Returns list of error strings."""
    errors = []

    if p <= 0:
        errors.append("p must be positive")
    if r <= 0:
        errors.append("r must be positive")
    if p <= 0 or r <= 0:
        return errors

    if not is_probable_prime(p):
        errors.append("p is not prime")
    if not is_probable_prime(r):
        errors.append("r is not prime")

    if family in FAMILY_POLYS:
        p_poly, r_poly = FAMILY_POLYS[family]
        expected_p = p_poly(u)
        if expected_p is None:
            errors.append("p formula undefined for this u (numerator not divisible by 3)")
        elif expected_p != p:
            errors.append(f"p does not match {family} formula for given u")
        expected_r = r_poly(u)
        if expected_r != r:
            errors.append(f"r does not match {family} formula for given u")
    else:
        errors.append(f"Unknown curve family: {family}")

    if is_probable_prime(p) and is_probable_prime(r) and r > 1:
        if pow(p, k, r) != 1:
            errors.append(f"r does not divide p^{k} - 1 (embedding degree condition fails)")
        else:
            for i in range(1, k):
                if k % i == 0:
                    if pow(p, i, r) == 1:
                        errors.append(
                            f"embedding degree not minimal: r divides p^{i} - 1"
                        )
                        break

    return errors


def compute_gt_security(p, k):
    """
    Compute GT DLP security in F_{p^k} using L-notation NFS estimates.

    Considers GNFS and Special-extended Tower NFS (SexTNFS) for each
    tower decomposition of k.
    """
    log_N = k * math.log(p)
    log_log_N = math.log(log_N)

    def l_bits(c):
        return (1.0 / math.log(2)) * c * (log_N ** (1.0 / 3)) * (log_log_N ** (2.0 / 3))

    # GNFS baseline: c = (64/9)^{1/3}
    c_gnfs = (64.0 / 9.0) ** (1.0 / 3.0)
    min_sec = l_bits(c_gnfs)

    # SexTNFS for each valid tower decomposition k = eta * kappa
    for eta in range(2, k):
        if k % eta == 0:
            kappa = k // eta
            if kappa > 1:
                c_sext = ((32.0 * (eta + 1)) / (9.0 * eta)) ** (1.0 / 3.0)
                sec = l_bits(c_sext)
                min_sec = min(min_sec, sec)

    return min_sec


def generate_verify_gp(curves_data, output_path):
    """Generate a PARI/GP verification script."""
    lines = [
        "default(linewrap, 0);",
        "",
        "\\\\ Family polynomial definitions",
        "bls12_pfun(u) = (u-1)^2 * (u^4 - u^2 + 1) / 3 + u;",
        "bls12_rfun(u) = u^4 - u^2 + 1;",
        "bn_pfun(u) = 36*u^4 + 36*u^3 + 24*u^2 + 6*u + 1;",
        "bn_rfun(u) = 36*u^4 + 36*u^3 + 18*u^2 + 6*u + 1;",
        "",
    ]

    for name, u, p, r, family in curves_data:
        lines.append(f"\\\\ {name}")
        lines.append("{")
        lines.append(f"  my_u = {u};")
        lines.append(f"  my_p = {p};")
        lines.append(f"  my_r = {r};")
        lines.append(f'  printf("{name}:p_prime:%d\\n", isprime(my_p));')
        lines.append(f'  printf("{name}:r_prime:%d\\n", isprime(my_r));')

        if family == "BLS12":
            lines.append(
                f'  printf("{name}:poly_consistent:%d\\n", '
                f"my_p == bls12_pfun(my_u) && my_r == bls12_rfun(my_u));"
            )
        elif family == "BN":
            lines.append(
                f'  printf("{name}:poly_consistent:%d\\n", '
                f"my_p == bn_pfun(my_u) && my_r == bn_rfun(my_u));"
            )

        lines.append("}")
        lines.append("")

    lines.append("\\q")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def audit():
    """Run the full audit pipeline."""
    with open("/app/manifest.toml", "rb") as f:
        manifest = tomllib.load(f)

    curves = manifest["curves"]
    results = []
    verify_data = []

    for curve_def in curves:
        name = curve_def["name"]
        family = curve_def["family"]
        k = curve_def["k"]
        claimed = curve_def["claimed_security_bits"]

        u, p, r = extract_params(curve_def)
        verify_data.append((name, u, p, r, family))

        errors = validate_curve(u, p, r, k, family)
        valid = len(errors) == 0

        result = {
            "name": name,
            "valid": valid,
            "validation_errors": errors,
        }

        if valid:
            g1_sec = math.log2(r) / 2.0
            gt_sec = compute_gt_security(p, k)
            overall = min(g1_sec, gt_sec)
            result["g1_security_bits"] = round(g1_sec, 2)
            result["gt_security_bits"] = round(gt_sec, 2)
            result["overall_security_bits"] = round(overall, 2)
            result["meets_claimed_level"] = int(overall) >= claimed
        else:
            result["g1_security_bits"] = None
            result["gt_security_bits"] = None
            result["overall_security_bits"] = None
            result["meets_claimed_level"] = False

        results.append(result)

    output = {"curves": results}
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    generate_verify_gp(verify_data, "/app/verify.gp")

    print("Audit complete. Results written to /app/results.json")
    print("Verification script written to /app/verify.gp")
    for r in results:
        status = "VALID" if r["valid"] else "INVALID"
        claim = "PASS" if r["meets_claimed_level"] else "FAIL"
        print(f"  {r['name']}: {status}, claim: {claim}")


if __name__ == "__main__":
    audit()
