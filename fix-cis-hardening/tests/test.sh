#!/bin/bash


# Install test dependencies
pip3 install pytest==8.3.4 -q

# Restore system to insecure baseline before running harden.sh
cp /app/.baseline/sshd_config /etc/ssh/sshd_config
cp /app/.baseline/90-override.conf /etc/ssh/sshd_config.d/90-override.conf
cp /app/.baseline/99-insecure.conf /etc/sysctl.d/99-insecure.conf
cp /app/.baseline/50-network.conf /etc/sysctl.d/50-network.conf
cp /app/.baseline/login.defs /etc/login.defs
cp /app/.baseline/pwquality.conf /etc/security/pwquality.conf
cp /app/.baseline/limits.conf /etc/security/limits.conf
cp /app/.baseline/sysctl.conf /etc/sysctl.conf

# Restore modprobe.d to default state
rm -rf /etc/modprobe.d
cp -r /app/.baseline/modprobe.d /etc/modprobe.d
rm -f /etc/modprobe.conf

# Remove any sysctl.d files the agent may have created (preserve baseline only)
for f in /etc/sysctl.d/*.conf; do
    [ "$f" = "/etc/sysctl.d/99-insecure.conf" ] && continue
    [ "$f" = "/etc/sysctl.d/50-network.conf" ] && continue
    rm -f "$f"
done

# Remove any sshd_config.d files the agent may have added (preserve baseline only)
for f in /etc/ssh/sshd_config.d/*.conf; do
    [ "$f" = "/etc/ssh/sshd_config.d/90-override.conf" ] && continue
    rm -f "$f"
done

# Reset file permissions to insecure state
chmod 0666 /etc/shadow
chown root:root /etc/shadow
chmod 0666 /etc/gshadow
chown root:root /etc/gshadow
chmod 0644 /etc/ssh/sshd_config

# Recreate banner
echo "Authorized users only. All activity is monitored and recorded." > /etc/issue.net

# Run the hardening script TWICE to verify idempotency
cd /app
bash /app/harden.sh
bash /app/harden.sh

# Run pytest
EXIT_CODE=0
python3 -m pytest /tests/test_state.py -v || EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
