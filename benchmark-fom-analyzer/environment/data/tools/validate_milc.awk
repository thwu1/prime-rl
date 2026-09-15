#!/usr/bin/awk -f
# validate_milc.awk - MILC lattice QCD benchmark validation and metric extraction
#
# Extracts trajectory-2 GFTIME statistics, computes OLCF-FOM, and validates
# the final-trajectory plaquette against a reference value.
#
# Usage:
#   awk -f validate_milc.awk \
#       -v ref_plaq=0.58791 -v tol_pct=0.1 -v traj_steps=80 \
#       <milc_log_file>
#
# Parameters (passed via -v):
#   ref_plaq   - reference plaquette value (default: 0.58791)
#   tol_pct    - tolerance in percent for plaquette deviation (default: 0.1)
#   traj_steps - number of steps per full trajectory for FOM projection (default: 80)
#
# Output: structured key=value pairs on stdout

BEGIN {
    if (ref_plaq == "") ref_plaq = 0.58791
    if (tol_pct == "") tol_pct = 0.1
    if (traj_steps == "") traj_steps = 80
    in_traj2 = 0
    gf_count = 0
    gf_sum = 0.0
    last_plaq = -1
    nodes = 0
}

/^Number of nodes:/ {
    nodes = $NF + 0
}

/BEGIN TRAJECTORY 2/ {
    in_traj2 = 1
    next
}

/END TRAJECTORY 2/ {
    in_traj2 = 0
    next
}

in_traj2 == 1 && /^GFTIME:/ && !/warmup/ {
    gf_sum += $4
    gf_count++
}

/^PLAQ:/ {
    last_plaq = $2 + 0.0
}

END {
    if (gf_count > 0) {
        mean_gf = gf_sum / gf_count
        proj_time = mean_gf * traj_steps
        olcf_fom = 3600.0 / proj_time
    } else {
        mean_gf = 0
        proj_time = 0
        olcf_fom = 0
    }

    if (last_plaq >= 0) {
        dev = (last_plaq - ref_plaq) / ref_plaq * 100.0
        if (dev < 0) dev = -dev
        if (dev < tol_pct) {
            validation = "PASS"
        } else {
            validation = "FAIL"
        }
    } else {
        dev = -1
        validation = "FAIL"
    }

    printf "MILC_VALIDATION_RESULT\n"
    printf "nodes=%d\n", nodes
    printf "traj2_mean_gftime=%.6f\n", mean_gf
    printf "traj2_gftime_count=%d\n", gf_count
    printf "projected_traj_time=%.6f\n", proj_time
    printf "olcf_fom=%.6f\n", olcf_fom
    printf "final_plaquette=%.5f\n", last_plaq
    printf "reference_plaquette=%.5f\n", ref_plaq
    printf "deviation_pct=%.5f\n", dev
    printf "validation=%s\n", validation
}
