#!/bin/bash

# Copy solution files into place
cp /solution/sysy_to_llvm.py /app/sysy_to_llvm.py
cp /solution/run_makefile /app/Makefile
cp /solution/sysy_run.sh /app/sysy_run

# Create the compiler wrapper
cat > /app/sysy_compiler << 'WRAPPER'
#!/bin/bash
exec python3 /app/sysy_to_llvm.py "$@"
WRAPPER
chmod +x /app/sysy_compiler
chmod +x /app/sysy_run

# Build the runtime bitcode
make -C /app
