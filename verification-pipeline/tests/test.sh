#!/bin/bash


pip3 install pytest==8.3.4 -q

# Diagnostic checks
echo "=== Environment check ==="
echo "pipeline.py exists: $(test -f /app/pipeline.py && echo YES || echo NO)"
echo "specs dir: $(ls /app/specs/*.xml 2>/dev/null | wc -l) XML files"
echo "roots dir: $(ls /app/roots/*.ROOT 2>/dev/null | wc -l) ROOT files"
echo "exclusions: $(test -f /app/config/exclusions.json && echo YES || echo NO)"
echo "parser_notes: $(test -f /app/parser_notes.py && echo YES || echo NO)"
echo "========================="

cd /app
python3 -m pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
