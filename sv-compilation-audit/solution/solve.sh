#!/bin/bash

set -e

cd /app

# ---------------------------------------------------------------
# Step 1: Fix Bug 1 — xbar_switch.sv: missing package import
#         Add 'import xbar_pkg::*;' in the ANSI module header
# ---------------------------------------------------------------
sed -i '/^module xbar_switch$/a\  import xbar_pkg::*;' \
    /app/design/rtl/xbar_switch.sv

# ---------------------------------------------------------------
# Step 2: Fix Bug 2 — top_xbar.sv: wrong struct field '.address'
#         should be '.addr'
# ---------------------------------------------------------------
sed -i 's/\.address/.addr/g' /app/design/top/top_xbar.sv

# ---------------------------------------------------------------
# Step 3: Fix Bug 3 (silent) — round_robin_arb.sv: typo
#         'masked_requests' creates an implicit net instead of
#         connecting the computed 'masked_req' signal
# ---------------------------------------------------------------
sed -i 's/masked_requests/masked_req/g' /app/design/rtl/round_robin_arb.sv

# ---------------------------------------------------------------
# Step 4: Fix Bug 4 (silent) — addr_decoder.sv: hardcoded [15:14]
#         Must use parameterized [ADDR_W-1:ADDR_W-SEL_W]
# ---------------------------------------------------------------
sed -i 's/addr\[15:14\]/addr[ADDR_W-1:ADDR_W-SEL_W]/g' \
    /app/design/rtl/addr_decoder.sv

# ---------------------------------------------------------------
# Step 5: Create the slang build command file
# ---------------------------------------------------------------
cat > /app/build.f << 'CMDFILE'
// Include path for xbar_defs.svh
-I /app/design/include

// Library directory for priority_enc.sv (auto-discovered)
--libdir /app/design/lib

// Source files in dependency order
/app/design/pkg/xbar_pkg.sv
/app/design/rtl/addr_decoder.sv
/app/design/rtl/round_robin_arb.sv
/app/design/rtl/xbar_switch.sv
/app/design/top/top_xbar.sv
CMDFILE

# ---------------------------------------------------------------
# Step 6: Create the warning policy file
#         Enable -Weverything, then suppress false positives
# ---------------------------------------------------------------
cat > /app/warning_policy.f << 'WPOLICY'
// Enable maximum warning coverage
-Weverything

// Suppress false-positive warnings for intentional design patterns:

// calc_sel_width is a utility function for downstream consumers
-Wno-unused-package-subroutine

// Wildcard import is intentional for clean access to package types
-Wno-unused-wildcard-import

// Several signals are assigned but unused in this partial implementation
// (raw_valid, route_valid, arb_grant, arb_valid)
-Wno-unused-but-set-variable

// DATA_W parameter exists for documentation; clk/rst_n ports reserved
// for future pipelining
-Wno-unused-parameter
-Wno-unused-port
WPOLICY

# ---------------------------------------------------------------
# Step 7: Verify clean compilation with warning policy
# ---------------------------------------------------------------
slang -f /app/build.f -f /app/warning_policy.f

# ---------------------------------------------------------------
# Step 8: Extract AST JSON and generate hierarchy report
# ---------------------------------------------------------------
slang -f /app/build.f --ast-json /app/ast_raw.json

python3 /solution/extract_hierarchy.py /app/ast_raw.json /app/hierarchy_report.json

# ---------------------------------------------------------------
# Step 9: Generate triage report
# ---------------------------------------------------------------
python3 /solution/generate_triage.py /app/triage_report.json
