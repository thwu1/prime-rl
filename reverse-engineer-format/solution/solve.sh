#!/bin/bash

# The solution reverse-engineers /app/oracle's binary serialization format
# using a combination of binary analysis tools and targeted probing.

###############################################################################
# PHASE 1: Static binary analysis — discover hidden capabilities
###############################################################################

echo "=== Phase 1: Static analysis of stripped binary ==="

# Scan string table for hidden subcommands and section references
echo "Scanning strings for hidden features..."
strings /app/oracle | grep -iE '(dump|tables|rpack|spec|diag|version|section)'

# Examine ELF section headers for non-standard sections
echo -e "\nELF section analysis:"
readelf -S /app/oracle | grep -iE '(rpack|spec|note)'

###############################################################################
# PHASE 2: Extract embedded format specification from ELF section
###############################################################################

echo -e "\n=== Phase 2: Extract embedded specification ==="

# Extract the .rpack_spec section from the binary
objcopy --dump-section .rpack_spec=/tmp/rpack_spec.bin /app/oracle

# Decompress (zlib) and display the embedded specification
python3 -c "
import zlib
data = open('/tmp/rpack_spec.bin', 'rb').read()
spec = zlib.decompress(data).decode()
print(spec)
"

###############################################################################
# PHASE 3: Use hidden diagnostic subcommand for CRC parameters
###############################################################################

echo -e "\n=== Phase 3: Extract CRC parameters via dump-tables ==="

# The embedded spec references 'dump-tables' for CRC parameters
/app/oracle dump-tables

###############################################################################
# PHASE 4: Targeted probing with xxd to confirm format details
###############################################################################

echo -e "\n=== Phase 4: Confirm format via targeted probing ==="

echo "Null encoding:"
echo -n 'null' | /app/oracle encode | xxd

echo "Integer 42:"
echo -n '42' | /app/oracle encode | xxd

echo "Float 3.14:"
echo -n '3.14' | /app/oracle encode | xxd

echo "String hello:"
echo -n '"hello"' | /app/oracle encode | xxd

echo "Array [1,2,3]:"
echo -n '[1,2,3]' | /app/oracle encode | xxd

echo "Object with reverse-sorted keys:"
echo -n '{"z":1,"a":2}' | /app/oracle encode | xxd

###############################################################################
# PHASE 5: Dynamic tracing to verify I/O behavior
###############################################################################

echo -e "\n=== Phase 5: Dynamic tracing ==="
strace -e trace=read,write,open,openat /app/oracle encode 2>&1 <<< '"test"' | head -30

###############################################################################
# PHASE 6: Install the reverse-engineered reimplementation
###############################################################################

echo -e "\n=== Phase 6: Install reimplementation ==="
cp /solution/reimpl.py /app/reimpl
chmod +x /app/reimpl

###############################################################################
# PHASE 7: Cross-validate against oracle
###############################################################################

echo -e "\n=== Phase 7: Cross-validation ==="
FAIL=0
for tc in 'null' 'true' 'false' '0' '1' '15' '16' '127' '128' '-1' '-128' '-129' \
          '32767' '32768' '-32768' '-32769' '2147483647' '2147483648' \
          '3.14' '-0.001' '1e100' \
          '""' '"hello"' '"hello world"' \
          '[]' '[1,2,3]' '[[1,2],[3,4]]' \
          '{}' '{"a":1}' '{"z":1,"a":2}'; do
    oracle_hex=$(echo "$tc" | /app/oracle encode | xxd -p | tr -d '\n')
    reimpl_hex=$(echo "$tc" | /app/reimpl encode | xxd -p | tr -d '\n')
    if [ "$oracle_hex" != "$reimpl_hex" ]; then
        echo "MISMATCH for $tc: oracle=$oracle_hex reimpl=$reimpl_hex"
        FAIL=1
    fi
done

if [ $FAIL -eq 0 ]; then
    echo "All cross-validation checks passed."
else
    echo "Some checks failed!"
    exit 1
fi
