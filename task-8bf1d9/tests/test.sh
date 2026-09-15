#!/bin/bash

# Restore git-index-pack for verification tests.
# The solver already ran without it (disabled in Dockerfile);
# anti-cheat is enforced by the independent pack test which
# temporarily re-disables it while running the solver's program.
if [ -f /usr/lib/git-core/.idx-pack-backup ]; then
    cp /usr/lib/git-core/.idx-pack-backup /usr/lib/git-core/git-index-pack
    chmod 755 /usr/lib/git-core/git-index-pack
fi

pip3 install pytest==8.3.4 -q

cd /app

pytest /tests/test_state.py -v --tb=short 2>&1
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
