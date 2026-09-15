#!/bin/bash

set -e

# Phase 1: Run binwalk reconnaissance scan
python3 /solution/solve_binwalk.py

# Phase 2: Extract ZIP archives from evidence container
python3 /solution/solve_extract.py

# Phase 3: Deploy the raw binary ZIP parser
cp /solution/zipforensics_solution.py /app/zipforensics.py

# Phase 4: Generate ssdeep fuzzy hashes
python3 /solution/solve_ssdeep.py

# Phase 5: Write YARA rules and run classification
python3 /solution/solve_yara.py

# Phase 6: Generate the consolidated forensic report
python3 /solution/solve_report.py

echo "=== Solution complete ==="
echo "Extracted specimens:"
ls -la /app/extracted/
echo ""
echo "Integrity manifest:"
cat /app/integrity.sha256
echo ""
echo "ssdeep hashes:"
cat /app/integrity.ssdeep
echo ""
echo "YARA results:"
cat /app/yara_results.json
echo ""
echo "Report:"
python3 -c "import json; print(json.dumps(json.load(open('/app/report.json')), indent=2))"
