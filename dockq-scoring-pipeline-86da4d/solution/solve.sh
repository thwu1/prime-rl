#!/bin/bash

set -e

cd /app

# 1. Copy adapted decoygen C source (CLI argument order fixed)
cp /solution/decoygen_adapted.c /app/decoygen_adapted.c

# 2. Create Makefile with proper tab indentation
{
echo 'CC = gcc'
echo 'CFLAGS = -O2'
echo 'LDFLAGS = -lm'
echo ''
echo 'all: decoygen calcrg'
echo ''
echo 'decoygen: decoygen_adapted.c'
printf '\t$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)\n'
echo ''
echo 'calcrg: reference/calcrg.cpp'
printf '\t$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)\n'
echo ''
echo 'clean:'
printf '\trm -f decoygen calcrg\n'
echo ''
echo '.PHONY: all clean'
} > /app/Makefile

# 3. Build C binaries
make -C /app all

# 4. Set up DockQ scorer (Python)
cp /solution/dockq.py /app/dockq.py

cat > /app/dockq << 'DOCKQ_EOF'
#!/bin/bash
python3 /app/dockq.py "$@"
DOCKQ_EOF
chmod +x /app/dockq

# 5. Create end-to-end pipeline script
cat > /app/score_all.sh << 'PIPELINE_EOF'
#!/bin/bash
# Score all poses from a MEGADOCK docking output
# Usage: score_all.sh <receptor.pdb> <ligand.pdb> <docking.out>

RECEPTOR=$1
LIGAND=$2
DOCKING_OUT=$3

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Create native complex from ATOM/HETATM lines only
grep "^ATOM\|^HETATM" "$RECEPTOR" > "$TMPDIR/native.pdb"
echo "TER" >> "$TMPDIR/native.pdb"
grep "^ATOM\|^HETATM" "$LIGAND" >> "$TMPDIR/native.pdb"
echo "END" >> "$TMPDIR/native.pdb"

# Get center-of-geometry for all poses via compiled calcrg
/app/calcrg "$DOCKING_OUT" 0 > "$TMPDIR/rg.csv"

# Count poses (lines after 4-line header)
NUM_POSES=$(tail -n +5 "$DOCKING_OUT" | wc -l)

# Determine chain IDs from PDB files
REC_CHAIN=$(grep "^ATOM" "$RECEPTOR" | head -1 | cut -c22)
LIG_CHAIN=$(grep "^ATOM" "$LIGAND" | head -1 | cut -c22)

# Score each pose
RESULTS=""
for i in $(seq 1 $NUM_POSES); do
    DECOY="$TMPDIR/decoy_${i}.pdb"
    MODEL="$TMPDIR/model_${i}.pdb"

    # Generate decoy ligand using compiled C binary
    /app/decoygen "$DOCKING_OUT" "$LIGAND" "$i" "$DECOY"

    # Create model complex
    grep "^ATOM\|^HETATM" "$RECEPTOR" > "$MODEL"
    echo "TER" >> "$MODEL"
    grep "^ATOM\|^HETATM" "$DECOY" >> "$MODEL"
    echo "END" >> "$MODEL"

    # Score with DockQ
    OUTPUT=$(/app/dockq "$TMPDIR/native.pdb" "$MODEL" --rec-chain "$REC_CHAIN" --lig-chain "$LIG_CHAIN")

    FNAT=$(echo "$OUTPUT" | grep "^fnat" | awk '{print $2}')
    LRMS=$(echo "$OUTPUT" | grep "^lrms" | awk '{print $2}')
    IRMS=$(echo "$OUTPUT" | grep "^irms" | awk '{print $2}')
    DOCKQ_VAL=$(echo "$OUTPUT" | grep "^dockq" | awk '{print $2}')
    CAPRI=$(echo "$OUTPUT" | grep "^capri" | awk '{print $2}')

    # Get center-of-geometry for this pose from calcrg output
    RG_LINE=$(sed -n "${i}p" "$TMPDIR/rg.csv" | tr -d ' ')
    RG_X=$(echo "$RG_LINE" | cut -d',' -f1)
    RG_Y=$(echo "$RG_LINE" | cut -d',' -f2)
    RG_Z=$(echo "$RG_LINE" | cut -d',' -f3)

    RESULTS="${RESULTS}${i}\t${FNAT}\t${LRMS}\t${IRMS}\t${DOCKQ_VAL}\t${CAPRI}\t${RG_X}\t${RG_Y}\t${RG_Z}\n"
done

# Print header and sorted results (sorted by dockq column descending)
echo -e "pose\tfnat\tlrms\tirms\tdockq\tcapri\trg_x\trg_y\trg_z"
echo -e "$RESULTS" | grep -v "^$" | sort -t$'\t' -k5 -rn
PIPELINE_EOF
chmod +x /app/score_all.sh
