#!/usr/bin/awk -f
#
# Converts USACE bathymetric survey files to JSON depth arrays.
# Input: whitespace-delimited (station, easting, northing, elevation_ft)
# Output: JSON array of {station, depth_m} objects
# Lines starting with # are comments; blank lines are skipped.
# Incomplete records (fewer than 4 fields) and non-positive depths are filtered.

BEGIN {
    printf "["
    first = 1
}

/^#/ { next }
/^[[:space:]]*$/ { next }
NF < 4 { next }

{
    station = $1
    elev_ft = $4 + 0.0
    depth_m = -elev_ft * 0.3048
    if (depth_m <= 0) next
    if (!first) printf ","
    printf "\n  {\"station\": \"%s\", \"depth_m\": %.4f}", station, depth_m
    first = 0
}

END {
    printf "\n]\n"
}
