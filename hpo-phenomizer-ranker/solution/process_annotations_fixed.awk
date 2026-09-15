#!/usr/bin/awk -f
# Process HPOA annotation file and emit SQL INSERT statements.
# FIXED version:
# - Uses correct variable name 'qualifier' (not 'qual') for NOT check
# - Filters to Aspect=P only
#
# Column layout (1-indexed):
#   1=DatabaseID  2=DiseaseName  3=Qualifier  4=HPO_ID
#   5=Reference   6=Evidence     7=Onset      8=Frequency
#   9=Sex        10=Modifier    11=Aspect    12=Biocuration


BEGIN {
    FS = "\t"
    OFS = "\t"
    accepted = 0
    rejected = 0
}

# Skip comment lines and header
/^#/  { next }
/^DatabaseID/ { next }

# Require at least 12 fields
NF < 12 { next }

{
    disease_id   = $1
    disease_name = $2
    qualifier    = $3
    hpo_id       = $4
    aspect       = $11

    # FIX: Filter non-phenotype annotations (only keep Aspect=P)
    if (aspect != "P") {
        rejected++
        next
    }

    # FIX: Use correct variable name 'qualifier' (was 'qual')
    if (qualifier == "NOT") {
        rejected++
        next
    }

    # Escape single quotes in disease names for SQL safety
    gsub(/'/, "''", disease_name)

    printf "INSERT OR IGNORE INTO annotations (disease_id, disease_name, hpo_id, qualifier, aspect) VALUES ('%s', '%s', '%s', '%s', '%s');\n", \
        disease_id, disease_name, hpo_id, qualifier, aspect
    accepted++
}

END {
    printf "-- Processed: %d accepted, %d rejected\n", accepted, rejected > "/dev/stderr"
}
