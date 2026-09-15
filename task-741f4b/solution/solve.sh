#!/bin/bash

# Install the compiler
mkdir -p /app/compiler
cp /solution/sysy_compiler.py /app/compiler/sysy_compiler.py

# Create the driver script that orchestrates the LLVM toolchain
cat > /app/sysy_run << 'DRIVER'
#!/bin/bash
# SysY compiler pipeline: compile -> link -> execute via LLVM toolchain
TMP=/tmp/sysy_$$
python3 /app/compiler/sysy_compiler.py "$1" > "${TMP}.ll" || { rm -f "${TMP}.ll"; exit 1; }
# Compile runtime library to bitcode (cached)
if [ ! -f /tmp/sylib.bc ]; then
    clang -c -emit-llvm -o /tmp/sylib.bc /app/runtime/sylib.c 2>/dev/null
fi
# Link generated IR with runtime library
llvm-link "${TMP}.ll" /tmp/sylib.bc -o "${TMP}.bc" 2>/dev/null || { rm -f "${TMP}.ll" "${TMP}.bc"; exit 1; }
# Execute via LLVM interpreter
lli "${TMP}.bc"
ST=$?
rm -f "${TMP}.ll" "${TMP}.bc"
exit $ST
DRIVER

chmod +x /app/sysy_run
