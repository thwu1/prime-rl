#!/usr/bin/env bash

set -euo pipefail

cd /app

##############################################################################
# Step 1: Install slang from GitHub releases
##############################################################################

echo "=== Installing slang ==="

RELEASE_JSON=$(curl -sL https://api.github.com/repos/MikePopoloski/slang/releases/latest)
TARBALL_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset['name'].lower()
    if 'linux' in name and name.endswith('.tar.gz'):
        print(asset['browser_download_url'])
        break
")

if [ -z "$TARBALL_URL" ]; then
    echo "ERROR: No Linux release asset found."
    exit 1
fi

echo "Downloading: $TARBALL_URL"
wget -q "$TARBALL_URL" -O /tmp/slang-linux.tar.gz
mkdir -p /tmp/slang-extract
tar xzf /tmp/slang-linux.tar.gz -C /tmp/slang-extract

SLANG_BIN=$(find /tmp/slang-extract -name "slang" -type f 2>/dev/null | head -1)
if [ -z "$SLANG_BIN" ]; then
    SLANG_BIN=$(find /tmp/slang-extract -name "slang" 2>/dev/null | head -1)
fi

if [ -n "$SLANG_BIN" ]; then
    chmod +x "$SLANG_BIN"
    cp "$SLANG_BIN" /usr/local/bin/slang
    EXTRACT_DIR=$(dirname "$SLANG_BIN")
    if [ -d "$EXTRACT_DIR/../lib" ]; then
        cp -r "$EXTRACT_DIR/../lib"/* /usr/local/lib/ 2>/dev/null || true
        ldconfig 2>/dev/null || true
    fi
else
    echo "ERROR: Could not find slang binary in archive"
    find /tmp/slang-extract -type f
    exit 1
fi

rm -rf /tmp/slang-linux.tar.gz /tmp/slang-extract

slang --version
echo "slang installed successfully"

##############################################################################
# Step 2: Create the command file
##############################################################################

echo "=== Creating compile.f ==="

cat > /app/compile.f << 'CMDFILE'
# slang command file for SoC design compilation

# Package must be compiled first
/opt/soc_design/pkg/soc_pkg.sv

# RTL source files
/opt/soc_design/rtl/alu.sv
/opt/soc_design/rtl/regfile.sv
/opt/soc_design/rtl/cpu_core.sv
/opt/soc_design/rtl/gpio_bank.sv
/opt/soc_design/rtl/soc_top.sv

# Include path for .svh header files
+incdir+/opt/soc_design/include

# Library directories for Verilog IP blocks (.v files)
-y /opt/soc_design/ip_lib/fifo
-y /opt/soc_design/ip_lib/serial
+libext+.v

# Top-level module
--top soc_top
CMDFILE

echo "compile.f created"

##############################################################################
# Step 3: Verify compilation
##############################################################################

echo "=== Verifying compilation ==="
slang -f /app/compile.f
echo "Compilation successful"

##############################################################################
# Step 4: Generate AST JSON
##############################################################################

echo "=== Generating AST JSON ==="
slang -f /app/compile.f --ast-json /app/ast.json
echo "AST JSON generated"

##############################################################################
# Step 5: Create and run the analysis script
##############################################################################

echo "=== Creating analyze.py ==="
cp /solution/analyze.py /app/analyze.py

echo "=== Running analysis ==="
python3 /app/analyze.py

echo "=== Done ==="
cat /app/analysis.json
