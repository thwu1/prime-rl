#!/bin/bash

# Copy the solution implementation into /app and build
cp /solution/nacl_vault.c /app/nacl_vault.c
make -C /app clean nacl_vault

if [ $? -ne 0 ]; then
    echo "ERROR: compilation failed"
    exit 1
fi

# Verify with a round-trip test
echo "=== Round-trip test ==="
/app/nacl_vault keygen /tmp/test.sk /tmp/test.pk
dd if=/dev/urandom of=/tmp/test_plain.bin bs=1 count=70000 2>/dev/null
/app/nacl_vault encrypt -r /tmp/test.pk -o /tmp/test.vault /tmp/test_plain.bin
/app/nacl_vault decrypt -k /tmp/test.sk -o /tmp/test_dec.bin /tmp/test.vault

if diff /tmp/test_plain.bin /tmp/test_dec.bin > /dev/null 2>&1; then
    echo "Round-trip OK (70000 bytes, multi-chunk)"
else
    echo "Round-trip FAILED"
    exit 1
fi

# Multi-recipient test
echo "=== Multi-recipient test ==="
/app/nacl_vault keygen /tmp/alice.sk /tmp/alice.pk
/app/nacl_vault keygen /tmp/bob.sk /tmp/bob.pk
echo "secret message" > /tmp/msg.txt
/app/nacl_vault encrypt -r /tmp/alice.pk -r /tmp/bob.pk -o /tmp/multi.vault /tmp/msg.txt
/app/nacl_vault decrypt -k /tmp/alice.sk -o /tmp/dec_a.txt /tmp/multi.vault
/app/nacl_vault decrypt -k /tmp/bob.sk -o /tmp/dec_b.txt /tmp/multi.vault

if diff /tmp/msg.txt /tmp/dec_a.txt > /dev/null 2>&1 && diff /tmp/msg.txt /tmp/dec_b.txt > /dev/null 2>&1; then
    echo "Multi-recipient OK"
else
    echo "Multi-recipient FAILED"
    exit 1
fi

echo "=== All solution checks passed ==="
