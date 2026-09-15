#!/usr/bin/env python3
"""
Download official GSW-C source code and generate a correct gsw_pipeline.c.

Uses multiple fallback strategies to obtain the TEOS-10 GSW-C
specific volume polynomial and its derivatives.

"""

import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.request
import glob as glob_mod

GSW_OUTPUT = "/tmp/gsw_pipeline_correct.c"


def download_via_pypi():
    """Download GSW source tarball via PyPI JSON API."""
    for version in ["3.6.16.post1", "3.6.16", "3.6.17", "3.6.18"]:
        try:
            url = f"https://pypi.org/pypi/gsw/{version}/json"
            req = urllib.request.Request(url, headers={"User-Agent": "python"})
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())

            for url_info in data.get("urls", []):
                if url_info.get("packagetype") == "sdist":
                    sdist_url = url_info["url"]
                    print(f"Downloading GSW {version} sdist from PyPI...")
                    urllib.request.urlretrieve(sdist_url, "/tmp/gsw.tar.gz")

                    os.makedirs("/tmp/gsw_extract", exist_ok=True)
                    with tarfile.open("/tmp/gsw.tar.gz") as tf:
                        tf.extractall("/tmp/gsw_extract")

                    for root, dirs, files in os.walk("/tmp/gsw_extract"):
                        if (
                            "gsw_oceanographic_toolbox.c" in files
                            and "gswteos-10.h" in files
                        ):
                            print(f"GSW-C source found at {root}")
                            return root

        except Exception as e:
            print(f"  PyPI {version}: {e}", file=sys.stderr)

    return None


def download_via_github():
    """Download GSW-C source files from GitHub."""
    url_sets = [
        (
            "https://raw.githubusercontent.com/TEOS-10/GSW-Python/v3.6.16/src/c_gsw",
            ["gsw_oceanographic_toolbox.c", "gswteos-10.h"],
        ),
        (
            "https://raw.githubusercontent.com/TEOS-10/GSW-Python/v3.6.16.post1/src/c_gsw",
            ["gsw_oceanographic_toolbox.c", "gswteos-10.h"],
        ),
        (
            "https://raw.githubusercontent.com/TEOS-10/GSW-Python/main/src/c_gsw",
            ["gsw_oceanographic_toolbox.c", "gswteos-10.h"],
        ),
        (
            "https://raw.githubusercontent.com/TEOS-10/GSW-C/master",
            ["gsw_oceanographic_toolbox.c", "gswteos-10.h"],
        ),
        (
            "https://raw.githubusercontent.com/TEOS-10/GSW-C/main",
            ["gsw_oceanographic_toolbox.c", "gswteos-10.h"],
        ),
    ]

    dest = "/tmp/gsw_github"
    os.makedirs(dest, exist_ok=True)

    for base_url, files in url_sets:
        ok = True
        for fname in files:
            url = f"{base_url}/{fname}"
            path = os.path.join(dest, fname)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "python"})
                urllib.request.urlretrieve(url, path)
                with open(path) as f:
                    head = f.read(200)
                if "<html" in head.lower() or "404" in head[:50] or len(head) < 100:
                    ok = False
                    break
            except Exception:
                ok = False
                break
        if ok:
            print(f"GSW-C source downloaded from {base_url}")
            return dest

    return None


def download_via_pip():
    """Download GSW source via pip download."""
    dest = "/tmp/gsw_pip_dl"
    os.makedirs(dest, exist_ok=True)

    try:
        subprocess.run(
            [
                "pip3", "download",
                "gsw>=3.6.16,<=3.6.18",
                "--no-binary", ":all:",
                "--no-deps",
                "-d", dest,
            ],
            capture_output=True,
            timeout=120,
        )

        tarballs = glob_mod.glob(os.path.join(dest, "gsw-*.tar.gz"))
        if tarballs:
            extract_dir = "/tmp/gsw_pip_extract"
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(tarballs[0]) as tf:
                tf.extractall(extract_dir)

            for root, dirs, files in os.walk(extract_dir):
                if (
                    "gsw_oceanographic_toolbox.c" in files
                    and "gswteos-10.h" in files
                ):
                    print(f"GSW-C source from pip at {root}")
                    return root
    except Exception as e:
        print(f"  pip download: {e}", file=sys.stderr)

    return None


# ---------- C source extraction ---------- #


def extract_function(source, func_name):
    """Extract a complete C function body by brace-counting."""
    patterns = [
        rf"(?:double|void|int)\s+{func_name}\s*\([^)]*\)\s*\{{",
    ]
    for pat in patterns:
        match = re.search(pat, source, re.DOTALL)
        if match:
            break
    else:
        return None

    start = match.start()
    brace_count = 0
    for i in range(match.end() - 1, len(source)):
        if source[i] == "{":
            brace_count += 1
        elif source[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                return source[start : i + 1]
    return None


def extract_defines(header_content):
    """Extract relevant #define macros from the GSW-C header."""
    needed = [
        "gsw_sfac",
        "gsw_offset",
        "GSW_TEOS10_CONSTANTS",
        "GSW_SPECVOL_COEFFICIENTS",
    ]

    defines = []
    lines = header_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        for name in needed:
            if re.match(rf"\s*#\s*define\s+{re.escape(name)}\b", line):
                macro_lines = [line]
                while line.rstrip().endswith("\\") and i + 1 < len(lines):
                    i += 1
                    line = lines[i]
                    macro_lines.append(line)
                defines.append("\n".join(macro_lines))
                break
        i += 1

    return "\n\n".join(defines)


def try_preprocess(gsw_dir):
    """Use gcc -E to expand all macros in the toolbox source."""
    src = os.path.join(gsw_dir, "gsw_oceanographic_toolbox.c")
    try:
        result = subprocess.run(
            ["gcc", "-E", "-w", "-I", gsw_dir, src],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and len(result.stdout) > 1000:
            preprocessed = "\n".join(
                ln for ln in result.stdout.split("\n") if not ln.startswith("#")
            )
            return preprocessed
    except Exception:
        pass
    return None


def generate_pipeline(gsw_dir):
    """Generate gsw_pipeline_correct.c from the downloaded GSW-C source."""
    header_path = os.path.join(gsw_dir, "gswteos-10.h")
    source_path = os.path.join(gsw_dir, "gsw_oceanographic_toolbox.c")

    with open(header_path) as f:
        header = f.read()
    with open(source_path) as f:
        source = f.read()

    specvol = None
    sab = None
    macro_defs = ""

    # Strategy 1: preprocess to expand all macros
    preprocessed = try_preprocess(gsw_dir)
    if preprocessed:
        specvol = extract_function(preprocessed, "gsw_specvol")
        sab = extract_function(preprocessed, "gsw_specvol_alpha_beta")
        if specvol and sab:
            macro_defs = "/* Macros expanded by preprocessor */"
            print("Using preprocessed extraction (Strategy 1)")

    # Strategy 2: extract macros from header + raw function bodies
    if not specvol or not sab:
        print("Using manual macro extraction (Strategy 2)")
        macro_defs = extract_defines(header)
        specvol = extract_function(source, "gsw_specvol")
        sab = extract_function(source, "gsw_specvol_alpha_beta")

    if not specvol:
        print("ERROR: Could not extract gsw_specvol", file=sys.stderr)
        sys.exit(1)
    if not sab:
        print("ERROR: Could not extract gsw_specvol_alpha_beta", file=sys.stderr)
        sys.exit(1)

    pipeline = f"""/*
 * TEOS-10 Seawater Thermodynamics Pipeline \u2014 Correct Implementation
 * Generated from GSW-C v3.06.16 source code.
 *
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "gsw_pipeline.h"

#ifndef GSW_INVALID_VALUE
#define GSW_INVALID_VALUE 9e90
#endif
#ifndef GSW_ERROR_LIMIT
#define GSW_ERROR_LIMIT 1e10
#endif

/* --- Definitions from GSW-C --- */
{macro_defs}

/* Sentinel check: compare using fabs for reliable detection */
int is_valid_value(double val) {{
    return (fabs(val) < GSW_ERROR_LIMIT);
}}

/* --- Specific volume from GSW-C --- */
{specvol}

/* --- Specific volume with alpha and beta from GSW-C --- */
{sab}

/* In-situ density */
double gsw_rho(double sa, double ct, double p) {{
    double v = gsw_specvol(sa, ct, p);
    if (v <= 0.0) return GSW_INVALID_VALUE;
    return 1.0 / v;
}}

/* Sigma0: potential density anomaly referenced to p = 0 */
double gsw_sigma0(double sa, double ct) {{
    return gsw_rho(sa, ct, 0.0) - 1000.0;
}}

/* Buoyancy frequency squared (N^2) */
void gsw_nsquared(const double *sa, const double *ct, const double *p,
                  const double *grav, int n, double *n2, double *p_mid) {{
    int i;
    double db_to_pa = 1e4;

    for (i = 0; i < n - 1; i++) {{
        double sa_mid, ct_mid, pm;
        double dp, dsa, dct;
        double v_mid, alpha_mid, beta_mid;
        double g_local;

        if (!is_valid_value(sa[i]) || !is_valid_value(sa[i+1]) ||
            !is_valid_value(ct[i]) || !is_valid_value(ct[i+1]) ||
            !is_valid_value(p[i])  || !is_valid_value(p[i+1])) {{
            n2[i] = GSW_INVALID_VALUE;
            p_mid[i] = GSW_INVALID_VALUE;
            continue;
        }}

        sa_mid = 0.5 * (sa[i] + sa[i+1]);
        ct_mid = 0.5 * (ct[i] + ct[i+1]);
        pm     = 0.5 * (p[i] + p[i+1]);
        dp     = p[i+1] - p[i];
        dsa    = sa[i+1] - sa[i];
        dct    = ct[i+1] - ct[i];

        gsw_specvol_alpha_beta(sa_mid, ct_mid, pm, &v_mid, &alpha_mid, &beta_mid);

        /* Use latitude-dependent gravity from the pre-computed array */
        g_local = 0.5 * (grav[i] + grav[i+1]);

        /* N^2 with correct dbar-to-Pa conversion */
        n2[i] = (g_local * g_local) / (v_mid * db_to_pa * dp)
                * (beta_mid * dsa - alpha_mid * dct);

        p_mid[i] = pm;
    }}
}}
"""

    with open(GSW_OUTPUT, "w") as f:
        f.write(pipeline)

    print(f"Correct pipeline written to {GSW_OUTPUT}")


def main():
    print("=== Downloading GSW-C source ===")

    gsw_dir = download_via_pypi()

    if not gsw_dir:
        print("PyPI failed, trying GitHub...")
        gsw_dir = download_via_github()

    if not gsw_dir:
        print("GitHub failed, trying pip download...")
        gsw_dir = download_via_pip()

    if not gsw_dir:
        print("ERROR: All download methods failed.", file=sys.stderr)
        sys.exit(1)

    # Verify key files
    for fname in ["gsw_oceanographic_toolbox.c", "gswteos-10.h"]:
        path = os.path.join(gsw_dir, fname)
        if not os.path.exists(path):
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    generate_pipeline(gsw_dir)


if __name__ == "__main__":
    main()
