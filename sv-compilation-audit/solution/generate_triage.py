#!/usr/bin/env python3
"""Generate the diagnostic triage report."""

import json
import sys


def main():
    output_path = sys.argv[1]

    report = {
        "compilation_errors": [
            {
                "file": "xbar_switch.sv",
                "description": (
                    "Module uses xbar_req_t and xbar_resp_t types in port "
                    "declarations without importing xbar_pkg. Produces 4 "
                    "cascading 'undeclared identifier' errors."
                ),
                "root_cause": (
                    "Missing 'import xbar_pkg::*;' in the ANSI module header. "
                    "Each file is a separate compilation unit in slang, so the "
                    "package must be explicitly imported within the module scope."
                ),
            },
            {
                "file": "top_xbar.sv",
                "description": (
                    "Port connection uses '.address' to access xbar_req_t "
                    "struct field, but the field is named '.addr'."
                ),
                "root_cause": (
                    "Struct field name mismatch: xbar_req_t defines 'addr' "
                    "not 'address'. This is a separate root cause from the "
                    "xbar_switch errors despite appearing in the same "
                    "compilation output."
                ),
            },
        ],
        "silent_bugs": [
            {
                "file": "round_robin_arb.sv",
                "description": (
                    "Port connection '.req(masked_requests)' references a "
                    "misspelled signal. SystemVerilog creates an implicit "
                    "1-bit net 'masked_requests' instead of erroring. The "
                    "computed signal 'masked_req' is never connected, so the "
                    "priority encoder receives a floating undriven net."
                ),
                "how_detected": (
                    "Running with -Weverything reveals: -Wunused-implicit-net "
                    "for 'masked_requests', -Wport-width-expand (1 to 4 bits), "
                    "and -Wunused-but-set-variable for 'masked_req'."
                ),
            },
            {
                "file": "addr_decoder.sv",
                "description": (
                    "Uses hardcoded bit-slice [15:14] instead of parameterized "
                    "[ADDR_W-1:ADDR_W-SEL_W]. With defaults (ADDR_W=16, "
                    "SEL_W=2), both evaluate identically so no error occurs. "
                    "Violates the parameterization contract in SPEC.md."
                ),
                "how_detected": (
                    "Running with -Weverything reveals -Wunused-parameter for "
                    "'SEL_W', indicating the localparam is computed but never "
                    "referenced. Cross-referencing with SPEC.md confirms the "
                    "bit-slice must be parameterized."
                ),
            },
        ],
        "false_positives": [
            {
                "warning_flag": "-Wno-unused-package-subroutine",
                "reason_suppressed": (
                    "calc_sel_width is a utility function retained for "
                    "downstream consumers per SPEC.md design intent."
                ),
            },
            {
                "warning_flag": "-Wno-unused-wildcard-import",
                "reason_suppressed": (
                    "Wildcard import of xbar_pkg is intentional for clean "
                    "access to package types in modules that use them."
                ),
            },
            {
                "warning_flag": "-Wno-unused-but-set-variable",
                "reason_suppressed": (
                    "Several signals (raw_valid, route_valid, arb_grant, "
                    "arb_valid) are assigned but unused in this partial "
                    "implementation. They are intentional placeholders."
                ),
            },
            {
                "warning_flag": "-Wno-unused-parameter",
                "reason_suppressed": (
                    "DATA_W parameter in xbar_switch exists for documentation "
                    "and external tool consumption per SPEC.md."
                ),
            },
            {
                "warning_flag": "-Wno-unused-port",
                "reason_suppressed": (
                    "clk and rst_n ports in xbar_switch are reserved for "
                    "future pipeline register insertion per SPEC.md."
                ),
            },
        ],
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Triage report written to {output_path}")


if __name__ == "__main__":
    main()
