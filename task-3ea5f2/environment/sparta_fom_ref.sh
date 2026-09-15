#!/bin/bash
# ATS-5 SPARTA FOM Extraction Pipeline
# Usage: sparta_fom.sh <logfile> [ranks_per_node]
#
# Extracts the Figure of Merit from a SPARTA log file per the ATS-5 benchmark
# specification. The FOM is the harmonic mean of per-timestep throughput
# (Mega-particle-steps/sec) from the statistics block between 300 and 600
# seconds of wall time, normalized by compute node count.
#
# Pipeline: awk (log parsing + filtering) -> awk (summation) -> bc (FOM calc)
#
# Based on the Crossroads/ATS-5 benchmark suite (v2.71).

set -euo pipefail

LOGFILE="${1:?Usage: $0 <logfile> [ranks_per_node]}"
RPN="${2:-112}"

if [ ! -f "$LOGFILE" ]; then
    echo "ERROR: File not found: $LOGFILE" >&2
    exit 1
fi

# Step 1: Extract MPI rank count from log header using awk
NRANKS=$(awk '/Running on.*MPI task\(s\)/{print $3; exit}' "$LOGFILE")
if [ -z "$NRANKS" ]; then
    echo "ERROR: Could not determine MPI rank count" >&2
    exit 1
fi
NNODES=$(echo "$NRANKS / $RPN" | bc)

# Step 2: Extract wall time from Loop time footer
WALL_TIME=$(awk '/Loop time of.*steps with/{printf "%.3f", $4; exit}' "$LOGFILE")
if [ -z "$WALL_TIME" ]; then
    echo "ERROR: Could not determine wall time" >&2
    exit 1
fi

# Verify minimum run duration (must be >= 600s)
BELOW_MIN=$(echo "$WALL_TIME < 600" | bc -l)
if [ "$BELOW_MIN" -eq 1 ]; then
    echo "ERROR: Wall time ${WALL_TIME}s is below 600s minimum" >&2
    exit 1
fi

# Step 3: Extract statistics rows in 300-600s CPU window using awk
# Compute reciprocals of QOI = Step * Np / CPU / 1e6 for harmonic mean
TMPFILE=$(mktemp /tmp/sparta_fom.XXXXXX)
trap "rm -f $TMPFILE" EXIT

awk '
/Step[[:space:]]+CPU[[:space:]]+Np[[:space:]]+Natt[[:space:]]+Ncoll[[:space:]]+Maxlevel/ {
    in_block = 1
    next
}
/Loop time of.*steps with/ {
    in_block = 0
    exit
}
in_block && NF == 6 {
    step = $1 + 0
    cpu  = $2 + 0
    np   = $3 + 0
    if (cpu >= 600) next
    if (cpu >= 300 && step > 0 && cpu > 0) {
        qoi = step * np / cpu / 1e6
        if (qoi > 0) printf "%.15e\n", 1.0 / qoi
    }
}
' "$LOGFILE" > "$TMPFILE"

N=$(wc -l < "$TMPFILE" | tr -d ' ')
if [ "$N" -eq 0 ]; then
    echo "ERROR: No valid data rows in 300-600s CPU window" >&2
    exit 1
fi

# Step 4: Aggregate reciprocals and compute harmonic mean / nodes via bc
SUM_RECIP=$(awk '{s += $1} END {printf "%.15e", s}' "$TMPFILE")
FOM=$(echo "scale=10; $N / ($SUM_RECIP) / $NNODES" | bc -l)

# Report
echo "================================================================"
echo "  SPARTA ATS-5 FOM Report"
echo "================================================================"
echo "  File:          $(realpath "$LOGFILE")"
echo "  MPI Ranks:     $NRANKS"
echo "  Compute Nodes: $NNODES"
echo "  Wall Time:     ${WALL_TIME} sec"
echo "  Samples:       $N"
echo "----------------------------------------------------------------"
printf "  FOM:           %s M-particle-steps/sec/node\n" "$FOM"
echo "================================================================"
