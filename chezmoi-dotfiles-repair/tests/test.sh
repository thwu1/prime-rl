#!/bin/bash

# Install test dependencies

# Install chezmoi
curl -fsLS get.chezmoi.io | sh -s -- -b /usr/local/bin

# Check fix script exists
if [ ! -f /app/fix_dotfiles.sh ]; then
    echo "ERROR: Fix script not found at /app/fix_dotfiles.sh"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the fix script
chmod +x /app/fix_dotfiles.sh
cd /app
bash /app/fix_dotfiles.sh
FIX_EXIT=$?
echo "Fix script exit code: $FIX_EXIT"

# Run chezmoi apply and capture exit code
chezmoi apply --source=/app/dotfiles --destination=/app/target --no-tty --force 2>&1
CHEZMOI_EXIT=$?
echo "$CHEZMOI_EXIT" > /tmp/chezmoi_exit_code
echo "chezmoi apply exit code: $CHEZMOI_EXIT"

# Run pytest
pytest /tests/test_state.py -v --tb=short
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
