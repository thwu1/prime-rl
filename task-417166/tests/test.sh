#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

# === Anti-cheat: verify COBOL source files have not been tampered with ===
sha256sum -c /opt/.cobol_sha256
if [ $? -ne 0 ]; then
    echo "FAIL: COBOL source files have been modified"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# === Anti-cheat: disable COBOL compiler before running agent code ===
# This prevents posting.py from shelling out to cobc to generate output.
COBC_DISABLED=""
for p in $(which -a cobc 2>/dev/null) /usr/bin/cobc /usr/local/bin/cobc; do
    if [ -f "$p" ] && [ ! -f "${p}.__disabled__" ]; then
        mv "$p" "${p}.__disabled__"
        COBC_DISABLED="$COBC_DISABLED $p"
    fi
done

# Remove any pre-compiled COBOL binaries the agent may have created
find /app /tmp /root /var/tmp -name "dailypost" -type f 2>/dev/null -exec rm -f {} \;
find /app /tmp /root /var/tmp -name "DAILYPOST" -type f 2>/dev/null -exec rm -f {} \;

# Clean any pre-existing output
rm -rf /app/output

# === Run agent's Python solution ===
cd /app
python3 /app/posting.py 2>&1 || true

# === Restore COBOL compiler ===
for p in $COBC_DISABLED; do
    if [ -f "${p}.__disabled__" ]; then
        mv "${p}.__disabled__" "$p"
    fi
done

# === Generate COBOL reference output dynamically ===
mkdir -p /tmp/cobol_ref/data /tmp/cobol_ref/output
cp /app/data/* /tmp/cobol_ref/data/

cobc -x -I /app/cobol/copybooks -o /tmp/cobol_ref/dailypost /app/cobol/DAILYPOST.cbl
if [ $? -ne 0 ]; then
    echo "COBOL reference compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /tmp/cobol_ref && ./dailypost
if [ $? -ne 0 ]; then
    echo "COBOL reference execution failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# === Run pytest comparing agent output against COBOL reference ===
cd /app
pytest_exit=0
python3 -m pytest /tests/test_state.py -v || pytest_exit=$?

mkdir -p /logs/verifier

if [ $pytest_exit -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $pytest_exit
