#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Compile PAM test helper
gcc -o /usr/local/bin/pam_test /tests/pam_test.c -lpam
chmod +x /usr/local/bin/pam_test

# Create minimal PAM service for testing (uses only common-auth and common-account)
echo '@include common-auth' > /etc/pam.d/test-auth
echo '@include common-account' >> /etc/pam.d/test-auth

# Ensure faillock data directory exists
mkdir -p /var/run/faillock

# Reset any faillock state before testing
faillock --reset 2>/dev/null || true

# Run tests
cd /tests
pytest test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
