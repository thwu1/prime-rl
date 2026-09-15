#!/bin/bash

set -e

# Deploy the resolver implementation
cp /solution/resolver_impl.py /app/resolve.py
chmod +x /app/resolve.py

echo "=== Resolver deployed. Running all manifests ==="

# Resolve each manifest to prove the solution works via computation
for manifest in /app/manifests/simple.json /app/manifests/diamond.json /app/manifests/deep.json /app/manifests/constrained.json; do
    echo ""
    echo "--- $(basename "$manifest") ---"
    python3 /app/resolve.py "$manifest"
done

echo ""
echo "--- conflict.json (expect CONFLICT with diagnostic) ---"
python3 /app/resolve.py /app/manifests/conflict.json 2>&1 || true

echo ""
echo "=== DIMACS export + MiniSat cross-validation ==="
for manifest in /app/manifests/diamond.json /app/manifests/conflict.json /app/manifests/deep.json; do
    name=$(basename "$manifest" .json)
    python3 /app/resolve.py --dimacs "$manifest" > "/tmp/${name}.cnf"
    echo -n "${name}: "
    minisat "/tmp/${name}.cnf" "/tmp/${name}_out.txt" > /dev/null 2>&1 || true
    head -1 "/tmp/${name}_out.txt"
done

echo ""
echo "=== All done ==="
